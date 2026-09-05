import asyncio
import logging
from typing import Any, Dict, List, Optional
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

logger = logging.getLogger("FunSearchService")

class FunSearchIsland:
    def __init__(self, island_id: int, max_capacity: int = 30):
        self.island_id = island_id
        self.max_capacity = max_capacity
        self.individuals: List[NSGA2Individual] = []

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
        self.islands: List[AsyncClusterIsland] = []
        self.tasks: List[asyncio.Task] = []
        self.dataset = get_benchmark_dataset()

        # Telemetry metrics
        self.total_evals_completed = 0
        self.top_fitness_score = 0.0
        self.champion_program: Optional[Program] = None
        self.active_islands_count = 0
        self.nsga2_islands = [FunSearchIsland(i) for i in range(self.num_islands)]
        self._lock = asyncio.Lock()

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "total_evals_completed": self.total_evals_completed,
            "top_fitness_score": round(self.top_fitness_score, 4),
            "champion_code": self.champion_program.code if self.champion_program else None,
            "champion_generation": self.champion_program.generation if self.champion_program else 0,
            "active_islands_count": len(self.islands),
            "islands": [
                {
                    "id": isl.island_id,
                    "best_fitness": isl.best_fitness if isl.best_fitness != -float("inf") else 0.0,
                    "clusters_count": len(isl.clusters),
                    "evals": isl.generation_count,
                    "strategy": isl.active_strategy.name
                }
                for isl in self.islands
            ]
        }

    async def start(self, evals_per_island: int = 20):
        if self.is_running:
            return
        self.is_running = True
        self.islands = [AsyncClusterIsland(i) for i in range(self.num_islands)]

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
        for island in self.islands:
            island.add_program(seed)

        self.top_fitness_score = seed.fitness
        self.champion_program = seed

        self.tasks = [
            asyncio.create_task(self._island_worker(island, evals_per_island))
            for island in self.islands
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
