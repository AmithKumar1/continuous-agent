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

logger = logging.getLogger("FunSearchService")

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

            # Mutation step via LLM or synthetic heuristic
            mutated_code = parents[0].code
            if self.client:
                try:
                    prompt = f"Improve this bin packing priority heuristic:\n```python\n{parents[0].code}\n```\nReturn code only."
                    resp = await self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=300
                    )
                    mutated_code = resp.choices[0].message.content or parents[0].code
                except Exception:
                    pass

            local_scope = {}
            try:
                exec(mutated_code, {}, local_scope)
                fn = local_scope.get("priority")
                if fn:
                    fp, ok = get_behavioral_fingerprint(fn)
                    fitness = run_simulation(fn, self.dataset)
                    prog = Program(
                        signature=fp,
                        code=mutated_code,
                        fitness=fitness,
                        generation=island.generation_count + 1,
                        char_length=len(mutated_code),
                        origin_island=island.island_id
                    )
                    _, is_best = island.add_program(prog)

                    async with self._lock:
                        self.total_evals_completed += 1
                        if fitness > self.top_fitness_score:
                            self.top_fitness_score = fitness
                            self.champion_program = prog

                    await broker.publish("funsearch_telemetry", self.get_telemetry())
            except Exception:
                pass

    def stop(self):
        self.is_running = False
        for t in self.tasks:
            t.cancel()
        logger.info("FunSearch service stopped.")

funsearch_service = FunSearchService()
