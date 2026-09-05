import asyncio
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from agent.prompt_strategies import PromptStrategy, STRATEGY_REGISTRY, mutate_strategy

@dataclass
class Program:
    signature: str
    code: str
    fitness: float
    generation: int
    char_length: int
    origin_island: int

class AsyncClusterIsland:
    def __init__(
        self,
        island_id: int,
        stagnation_limit: int = 15,
        temperature_init: float = 1.0,
        initial_strategy: Optional[PromptStrategy] = None
    ):
        self.island_id = island_id
        self.stagnation_limit = stagnation_limit
        self.temperature = temperature_init
        self.active_strategy = initial_strategy or random.choice(STRATEGY_REGISTRY)

        self.clusters: Dict[str, Program] = {}
        self.generations_without_improvement = 0
        self.best_fitness = -float("inf")
        self.generation_count = 0
        self.inbox: asyncio.Queue = asyncio.Queue()

    def add_program(self, program: Program) -> Tuple[bool, bool]:
        self.generation_count += 1
        is_global_best = False
        sig = program.signature

        if program.fitness > self.best_fitness:
            self.best_fitness = program.fitness
            self.generations_without_improvement = 0
            is_global_best = True
        else:
            self.generations_without_improvement += 1

        if sig not in self.clusters:
            self.clusters[sig] = program
            return True, is_global_best

        # Parsimony pressure: keep shorter program on fitness tie
        current = self.clusters[sig]
        if program.fitness > current.fitness:
            self.clusters[sig] = program
            return True, is_global_best
        elif math.isclose(program.fitness, current.fitness, abs_tol=1e-5):
            if program.char_length < current.char_length:
                self.clusters[sig] = program
                return True, is_global_best

        return False, is_global_best

    def check_stagnation_and_adapt(self) -> Tuple[bool, Optional[str]]:
        if self.generations_without_improvement >= self.stagnation_limit:
            old_strategy = self.active_strategy.name
            self.active_strategy = mutate_strategy(self.active_strategy)
            self.generations_without_improvement = 0
            self.temperature = min(2.5, self.temperature * 1.5)
            return True, f"Shifted strategy: {old_strategy} -> {self.active_strategy.name}"
        return False, None

    def sample_parents(self) -> List[Program]:
        if not self.clusters:
            return []
        items = list(self.clusters.values())
        k = min(len(items), 2)
        return random.sample(items, k)

    async def drain_inbox(self) -> int:
        ingested = 0
        while not self.inbox.empty():
            prog = await self.inbox.get()
            is_new, _ = self.add_program(prog)
            if is_new:
                ingested += 1
            self.inbox.task_done()
        return ingested
