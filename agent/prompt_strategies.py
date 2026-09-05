import random
from dataclasses import dataclass
from typing import List

@dataclass(frozen=True)
class PromptStrategy:
    name: str
    directive: str
    temperature: float
    top_p: float

STRATEGY_REGISTRY: List[PromptStrategy] = [
    PromptStrategy(
        name="greedy_local",
        directive="Introduce minimal, micro-optimizing algebraic edits to the heuristic. Avoid rewriting logic.",
        temperature=0.2,
        top_p=0.85
    ),
    PromptStrategy(
        name="structural_pivot",
        directive="Dramatically pivot the mathematical strategy. Use non-linear curves, ratios, or penalties.",
        temperature=0.85,
        top_p=0.95
    ),
    PromptStrategy(
        name="chain_of_thought",
        directive="Reason step-by-step about residual bin capacities before returning the final mathematical formula.",
        temperature=0.5,
        top_p=0.90
    ),
    PromptStrategy(
        name="sparse_ablation",
        directive="Strip all complex terms and prune parameters to find an ultra-minimal core equation.",
        temperature=0.3,
        top_p=0.80
    )
]

def mutate_strategy(current_strategy: PromptStrategy, available: List[PromptStrategy] = STRATEGY_REGISTRY) -> PromptStrategy:
    pool = [s for s in available if s.name != current_strategy.name]
    return random.choice(pool) if pool else current_strategy
