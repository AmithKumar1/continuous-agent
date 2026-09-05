import asyncio
import copy
import logging
from typing import Any, Dict, List, Optional, Tuple
from openai import AsyncOpenAI
from config import config
from agent.events import broker
from agent.restartable_island import AsyncClusterIsland, Program
from agent.prompt_strategies import STRATEGY_REGISTRY
from problem import INITIAL_HEURISTIC, PROGRAM_SKELETON, get_benchmark_dataset, run_simulation
from behavior import get_behavioral_fingerprint
from agent.expression_mutator import expression_mutator
from agent.staged_pipeline import staged_pipeline

import aiosqlite
from agent.db import get_db
from agent.nsga2 import (
    NSGA2Individual,
    nsga2_truncate,
    crowded_tournament_select,
    fast_non_dominated_sort,
    assign_crowding_distance
)
from agent.adaptive_sampling import calculate_adaptive_policy, SamplingPolicy
from agent.adaptive_temperature import calculate_adaptive_temperature, TemperatureConfig
from agent.island_profiler import calculate_phenotypic_entropy
from agent.audit_logger import record_policy_transition, record_beam_evaluation
from agent.metrics import (
    ISLAND_SAMPLING_TEMPERATURE,
    ISLAND_TOP_P,
    ISLAND_MUTATION_BEAM_WIDTH
)

logger = logging.getLogger("FunSearchService")

class FunSearchIsland:
    def __init__(self, island_id: int, max_capacity: int = 30):
        self.island_id = island_id
        self.max_capacity = max_capacity
        self.individuals: List[NSGA2Individual] = []
        self.current_temperature: float = 0.20
        self.current_policy = SamplingPolicy(temperature=0.20, top_p=0.70, beam_width=1)
        self.prompt_paradigm: str = "STANDARD"

    def compute_current_temperature(self) -> float:
        """Derives the current generation temperature from recent population entropy."""
        signatures = [ind.phenotype_signature for ind in self.individuals[-25:]]
        entropy = calculate_phenotypic_entropy(signatures)
        self.current_temperature = calculate_adaptive_temperature(entropy)
        
        # Stream updated temperature to Prometheus
        ISLAND_SAMPLING_TEMPERATURE.labels(island_id=str(self.island_id)).set(self.current_temperature)
        return self.current_temperature

    def refresh_sampling_policy(self) -> SamplingPolicy:
        """Computes current diversity entropy and updates sampling policy gauges."""
        signatures = [ind.phenotype_signature for ind in self.individuals[-25:]]
        entropy = calculate_phenotypic_entropy(signatures)
        self.current_policy = calculate_adaptive_policy(entropy)

        # Update telemetry
        i_str = str(self.island_id)
        ISLAND_SAMPLING_TEMPERATURE.labels(island_id=i_str).set(self.current_policy.temperature)
        ISLAND_TOP_P.labels(island_id=i_str).set(self.current_policy.top_p)
        ISLAND_MUTATION_BEAM_WIDTH.labels(island_id=i_str).set(self.current_policy.beam_width)

        return self.current_policy

    async def update_and_audit_policy(self) -> Tuple[SamplingPolicy, float]:
        """Calculates current entropy and persists state shifts to supervisor_policy_audit."""
        signatures = [ind.phenotype_signature for ind in self.individuals[-25:]]
        entropy = calculate_phenotypic_entropy(signatures)
        new_policy = calculate_adaptive_policy(entropy)

        temp_delta = abs(new_policy.temperature - self.current_policy.temperature)
        top_p_delta = abs(new_policy.top_p - self.current_policy.top_p)
        beam_changed = new_policy.beam_width != self.current_policy.beam_width

        if temp_delta >= 0.05 or top_p_delta >= 0.05 or beam_changed:
            await record_policy_transition(
                island_id=self.island_id,
                entropy=entropy,
                old_policy=self.current_policy,
                new_policy=new_policy
            )
            self.current_policy = new_policy

        return self.current_policy, entropy

    async def step_mutation(self) -> Optional[str]:
        """Dispatches mutation with temperature tuned to current diversity levels."""
        temp = self.compute_current_temperature()
        parents = self.sample_prompt_exemplars(count=2)
        if not parents:
            return None
        return await expression_mutator.mutate_expression(
            parent_code=parents[0].code,
            exemplars=[{"code": p.code, "fitness": p.packing_ratio} for p in parents],
            temperature=temp
        )

    async def step_mutation_beam(self) -> List[str]:
        """
        Executes an adaptive mutation step:
        Samples parents via NSGA-II crowded tournament selection and emits K candidate mutations.
        """
        policy = self.refresh_sampling_policy()
        parents = self.sample_prompt_exemplars(count=2)
        if not parents:
            return []

        return await expression_mutator.mutate_expression_beam(
            parent_code=parents[0].code,
            exemplars=[{"code": p.code, "fitness": p.packing_ratio} for p in parents],
            temperature=policy.temperature,
            top_p=policy.top_p,
            beam_width=policy.beam_width
        )

    async def step_mutation_beam_audited(self) -> List[str]:
        """Runs parallel beam mutations and logs candidate yields and acceptance counts."""
        policy, entropy = await self.update_and_audit_policy()
        parents = self.sample_prompt_exemplars(count=2)
        if not parents:
            return []

        raw_candidates = await expression_mutator.mutate_expression_beam(
            parent_code=parents[0].code,
            exemplars=[{"code": p.code, "fitness": p.packing_ratio} for p in parents],
            temperature=policy.temperature,
            top_p=policy.top_p,
            beam_width=policy.beam_width
        )

        accepted_candidates: List[str] = []
        rejection_reasons = []

        for code in raw_candidates:
            if "def " in code or "return" in code:
                accepted_candidates.append(code)
            else:
                rejection_reasons.append("syntax_error")

        await record_beam_evaluation(
            island_id=self.island_id,
            entropy=entropy,
            policy=policy,
            candidates_generated=len(raw_candidates),
            candidates_accepted=len(accepted_candidates),
            details={"rejections": rejection_reasons, "parent_ids": [p.id for p in parents]}
        )

        return accepted_candidates

    def register_heuristic(
        self,
        heuristic_id: str,
        code: str,
        packing_ratio: float,
        fuel_consumed: int,
        phenotype_signature: str
    ):
        """Registers an evaluated candidate and triggers NSGA-II truncation on overflow."""
        ind = NSGA2Individual(
            id=heuristic_id,
            code=code,
            packing_ratio=packing_ratio,
            fuel_consumed=fuel_consumed,
            phenotype_signature=phenotype_signature
        )
        self.individuals.append(ind)

        # Capacity management: preserve Pareto-optimal and diverse solutions
        if len(self.individuals) > self.max_capacity:
            self.individuals = nsga2_truncate(self.individuals, self.max_capacity)

    def sample_prompt_exemplars(self, count: int = 2) -> List[NSGA2Individual]:
        """
        Samples parent exemplars for LLM expression mutation.
        Ranks population via NSGA-II, then uses crowded tournament selection.
        """
        if len(self.individuals) <= count:
            return list(self.individuals)

        # Recalculate ranks and crowding distances across current survivors
        fronts = fast_non_dominated_sort(self.individuals)
        for front in fronts:
            assign_crowding_distance(front)

        selected: List[NSGA2Individual] = []
        for _ in range(count):
            winner = crowded_tournament_select(self.individuals, tournament_size=3)
            selected.append(winner)

        return selected

    def get_pareto_front(self) -> List[NSGA2Individual]:
        """Returns the active non-dominated frontier (Rank 1)."""
        if not self.individuals:
            return []
        fronts = fast_non_dominated_sort(self.individuals)
        return fronts[0] if fronts else []

async def persist_individual(db: aiosqlite.Connection, ind: NSGA2Individual, island_id: int, gen: int):
    """Saves or updates individual state with its NSGA-II frontier metrics."""
    await db.execute(
        """
        INSERT INTO heuristics (
            id, island_id, generation, code, fitness, wasm_fuel, 
            phenotype_signature, pareto_rank, crowding_distance
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            pareto_rank = excluded.pareto_rank,
            crowding_distance = excluded.crowding_distance;
        """,
        (
            ind.id,
            island_id,
            gen,
            ind.code,
            ind.packing_ratio,
            ind.fuel_consumed,
            ind.phenotype_signature,
            ind.rank,
            ind.crowding_distance if ind.crowding_distance != float("inf") else 1e9
        )
    )
    await db.commit()

class FunSearchService:
    def __init__(self, num_islands: int = 4):
        self.num_islands = num_islands
        self.client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.is_running = False
        self.islands: Dict[int, FunSearchIsland] = {i: FunSearchIsland(i) for i in range(self.num_islands)}
        self.nsga2_islands = list(self.islands.values())
        self.cluster_islands = [AsyncClusterIsland(i) for i in range(self.num_islands)]
        self.tasks: List[asyncio.Task] = []
        self.dataset = get_benchmark_dataset()

        # Telemetry metrics
        self.total_evals_completed = 0
        self.top_fitness_score = 0.0
        self.champion_program: Optional[Program] = None
        self.active_islands_count = 0
        self._lock = asyncio.Lock()

    async def execute_ring_migration(self, elite_count: int = 2):
        """
        Transfers non-dominated Pareto exemplars along a directed ring topology:
        Island i -> Island (i + 1) % N.
        Injects novel behavioral phenotypes without discarding accumulated fitness.
        """
        island_dict = self.islands if isinstance(self.islands, dict) else {
            isl.island_id: isl for isl in self.islands
        }
        island_ids = sorted(list(island_dict.keys()))
        if len(island_ids) < 2:
            logger.info("Fewer than 2 islands active; ring migration bypassed.")
            return

        migrants: Dict[int, List[NSGA2Individual]] = {}

        # 1. Collect top-ranked individuals from each island
        for i_id in island_ids:
            island = island_dict[i_id]
            pareto_front = island.get_pareto_front()
            if not pareto_front:
                pareto_front = sorted(island.individuals, key=lambda x: x.packing_ratio, reverse=True)

            # Select top elites by crowding distance
            assign_crowding_distance(pareto_front)
            selected = sorted(pareto_front, key=lambda x: x.crowding_distance, reverse=True)[:elite_count]
            migrants[i_id] = [copy.deepcopy(ind) for ind in selected]

        # 2. Inject migrants into downstream neighboring islands
        async with get_db() as db:
            for idx, src_id in enumerate(island_ids):
                target_id = island_ids[(idx + 1) % len(island_ids)]
                target_island = island_dict[target_id]

                for ind in migrants[src_id]:
                    # Retain code and performance, assign to target island
                    ind.id = f"{ind.id}_migrated_i{src_id}_to_i{target_id}"
                    target_island.register_heuristic(
                        heuristic_id=ind.id,
                        code=ind.code,
                        packing_ratio=ind.packing_ratio,
                        fuel_consumed=ind.fuel_consumed,
                        phenotype_signature=ind.phenotype_signature
                    )
                    # Persist migration transfer
                    await db.execute(
                        """
                        INSERT INTO heuristics (
                            id, island_id, generation, code, fitness, wasm_fuel,
                            phenotype_signature, pareto_rank, crowding_distance
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET island_id = excluded.island_id;
                        """,
                        (ind.id, target_id, 0, ind.code, ind.packing_ratio, ind.fuel_consumed,
                         ind.phenotype_signature, ind.rank, ind.crowding_distance if ind.crowding_distance != float("inf") else 1e9)
                    )
            await db.commit()

        logger.info(f"✓ Ring migration complete across {len(island_ids)} islands ({elite_count} elites/island).")

    async def execute_cataclysmic_restart(self, island_id: int, keep_pareto_elites: int = 1):
        """
        Breaks severe stagnation by purging non-Pareto individuals, preserving only
        the absolute best non-dominated solutions, and reseeding with divergent prompt paradigms.
        """
        island_dict = self.islands if isinstance(self.islands, dict) else {
            isl.island_id: isl for isl in self.islands
        }
        island = island_dict.get(island_id)
        if not island or not island.individuals:
            return

        # 1. Extract and preserve the primary Pareto frontier
        pareto_front = island.get_pareto_front()
        if not pareto_front:
            pareto_front = sorted(island.individuals, key=lambda x: x.packing_ratio, reverse=True)

        survivors = copy.deepcopy(pareto_front[:keep_pareto_elites])
        evicted_count = len(island.individuals) - len(survivors)

        # 2. Purge island memory to reset phenotypic entropy
        island.individuals = survivors

        # 3. Mutate island prompt strategy to explore orthogonal search spaces
        if not hasattr(island, "prompt_paradigm"):
            island.prompt_paradigm = "STANDARD"

        alternate_paradigms = ["INVERSE_FIT_DIVERGENCE", "STOCHASTIC_SCATTER", "COMPACT_GREEDY"]
        current_idx = alternate_paradigms.index(island.prompt_paradigm) if island.prompt_paradigm in alternate_paradigms else -1
        island.prompt_paradigm = alternate_paradigms[(current_idx + 1) % len(alternate_paradigms)]

        logger.warning(
            f"⚡ Cataclysmic restart on Island {island_id}: Evicted {evicted_count} stagnant individuals. "
            f"Preserved {len(survivors)} Pareto elite(s). Switched paradigm to '{island.prompt_paradigm}'."
        )

    def get_telemetry(self) -> Dict[str, Any]:
        isl_list = self.cluster_islands if hasattr(self, "cluster_islands") else (
            list(self.islands.values()) if isinstance(self.islands, dict) else self.islands
        )
        return {
            "is_running": self.is_running,
            "total_evals_completed": self.total_evals_completed,
            "top_fitness_score": round(self.top_fitness_score, 4),
            "champion_code": self.champion_program.code if self.champion_program else None,
            "champion_generation": self.champion_program.generation if self.champion_program else 0,
            "active_islands_count": len(isl_list),
            "islands": [
                {
                    "id": getattr(isl, "island_id", idx),
                    "best_fitness": getattr(isl, "best_fitness", 0.0) if getattr(isl, "best_fitness", 0.0) != -float("inf") else 0.0,
                    "clusters_count": len(getattr(isl, "clusters", [])),
                    "evals": getattr(isl, "generation_count", 0),
                    "strategy": getattr(getattr(isl, "active_strategy", None), "name", "DEFAULT")
                }
                for idx, isl in enumerate(isl_list)
            ]
        }

    async def start(self, evals_per_island: int = 20):
        if self.is_running:
            return
        self.is_running = True
        self.cluster_islands = [AsyncClusterIsland(i) for i in range(self.num_islands)]

        # Seed initial program into all islands
        fp, _ = get_behavioral_fingerprint(lambda item, cap: 1.0)
        seed = Program(
            signature=fp,
            code=INITIAL_HEURISTIC,
            fitness=run_simulation(lambda item, cap: 1.0, self.dataset),
            generation=0,
            char_length=len(INITIAL_HEURISTIC),
            origin_island=-1
        )
        for island in self.cluster_islands:
            island.add_program(seed)

        self.top_fitness_score = seed.fitness
        self.champion_program = seed

        self.tasks = [
            asyncio.create_task(self._island_worker(island, evals_per_island))
            for island in self.cluster_islands
        ]
        logger.info("FunSearch evolutionary service started.")

    async def _island_worker(self, island: AsyncClusterIsland, max_evals: int):
        for _ in range(max_evals):
            if not self.is_running:
                break

            await asyncio.sleep(0.5)
            parents = island.sample_parents()
            if not parents:
                continue

            # Mutation step via Two-Tier Expression Mutator or synthetic heuristic mutation
            mutated_code = await expression_mutator.mutate_expression(
                parents[0].code,
                strategy=island.active_strategy
            )
            if not mutated_code:
                mutated_code = self._synthetic_mutation(parents[0].code, island.island_id)

            # Evaluate through Staged Fail-Fast Pipeline
            diag = staged_pipeline.evaluate(mutated_code, self.dataset, island_id=island.island_id)

            if diag.success and diag.fitness > 0.0:
                try:
                    local_scope = {}
                    from agent.ast_guard import sanitize_ast
                    sanitize_ast(mutated_code)
                    exec(mutated_code, {}, local_scope)
                    fn = local_scope.get("priority")
                    if fn:
                        fp, _ = get_behavioral_fingerprint(fn)
                        prog = Program(
                            signature=fp,
                            code=mutated_code,
                            fitness=diag.fitness,
                            generation=island.generation_count + 1,
                            char_length=len(mutated_code),
                            origin_island=island.island_id
                        )
                        _, is_best = island.add_program(prog)

                        async with self._lock:
                            self.total_evals_completed += 1
                            if diag.fitness > self.top_fitness_score:
                                self.top_fitness_score = diag.fitness
                                self.champion_program = prog

                        # NSGA-II population management & persistence
                        try:
                            fuel = int(getattr(diag, "wasm_fuel", 0) or max(int(getattr(diag, "execution_time_ms", 1.0) * 100), 50))
                            nsga2_isl = self.nsga2_islands[island.island_id]
                            h_id = f"h_isl{island.island_id}_gen{island.generation_count}_{fp[:8]}"
                            nsga2_isl.register_heuristic(
                                heuristic_id=h_id,
                                code=mutated_code,
                                packing_ratio=diag.fitness,
                                fuel_consumed=fuel,
                                phenotype_signature=fp
                            )
                            async with get_db() as db:
                                ind_match = next((ind for ind in nsga2_isl.individuals if ind.id == h_id), None)
                                if ind_match:
                                    await persist_individual(db, ind_match, island.island_id, island.generation_count + 1)
                        except Exception as db_err:
                            logger.debug(f"Could not persist heuristic to db: {db_err}")

                        await broker.publish("funsearch_telemetry", self.get_telemetry())
                except Exception as eval_exc:
                    logger.debug(f"Fingerprinting/island update skipped: {eval_exc}")
            else:
                logger.debug(f"Candidate rejected at stage: {diag.origin} - {diag.detail}")

    def _synthetic_mutation(self, base_code: str, island_id: int) -> str:
        import random
        variants = [
            "def priority(item: float, bin_capacity: float) -> float:\n    # Ratio priority with capacity guard\n    return item / max(bin_capacity, 0.001)",
            "def priority(item: float, bin_capacity: float) -> float:\n    # Best-fit quadratic scaling\n    return (item ** 1.5) / (bin_capacity + 1e-5)",
            "def priority(item: float, bin_capacity: float) -> float:\n    # Tight fit bonus heuristic\n    residual = bin_capacity - item\n    return item * 2.0 - residual if residual >= 0 else -1.0",
            "def priority(item: float, bin_capacity: float) -> float:\n    # Harmonic priority balancing\n    return item / (bin_capacity + 0.5) + (item * 0.1)",
            "def priority(item: float, bin_capacity: float) -> float:\n    # First-fit descending ratio\n    return item / (bin_capacity if bin_capacity > item else 100.0)"
        ]
        return random.choice(variants)

    def stop(self):
        self.is_running = False
        for t in self.tasks:
            t.cancel()
        logger.info("FunSearch service stopped.")

funsearch_service = FunSearchService()
