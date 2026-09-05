import math
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

@dataclass
class HeuristicPoint:
    id: str
    island_id: int
    code: str
    packing_ratio: float  # Maximize
    fuel_consumed: int    # Minimize
    generation: int
    phenotype_signature: str
    is_pareto: bool = False

@dataclass
class IslandHealth:
    island_id: int
    total_evaluations: int
    best_fitness: float
    mean_fitness: float
    phenotypic_entropy: float
    is_plateaued: bool
    stagnation_generations: int
    suggested_action: str  # "NOMINAL", "RING_MIGRATION", "CATACLYSMIC_RESTART"

def compute_pareto_frontier(candidates: List[HeuristicPoint]) -> List[HeuristicPoint]:
    """
    Computes 2D Pareto-optimal frontier in O(N log N).
    Objectives: Maximize packing_ratio, Minimize fuel_consumed.
    """
    if not candidates:
        return []

    # Sort primarily by fuel_consumed ascending, secondarily by packing_ratio descending
    sorted_points = sorted(
        candidates,
        key=lambda x: (x.fuel_consumed, -x.packing_ratio)
    )

    pareto_front: List[HeuristicPoint] = []
    max_packing = -1.0

    for candidate in sorted_points:
        # If this candidate achieves a strictly higher packing ratio than any faster algorithm
        if candidate.packing_ratio > max_packing:
            candidate.is_pareto = True
            pareto_front.append(candidate)
            max_packing = candidate.packing_ratio
        else:
            candidate.is_pareto = False

    return pareto_front

def calculate_phenotypic_entropy(phenotypes: List[str]) -> float:
    """Calculates Shannon entropy across discrete phenotypic placement clusters."""
    if not phenotypes:
        return 0.0

    total = len(phenotypes)
    counts: Dict[str, int] = {}
    for p in phenotypes:
        counts[p] = counts.get(p, 0) + 1

    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy

def profile_island(
    island_id: int,
    history: List[Dict[str, Any]],
    window_size: int = 20,
    epsilon: float = 0.0005,
    entropy_threshold: float = 0.6
) -> IslandHealth:
    """Evaluates stagnation and entropy decay for a single evolutionary island."""
    total_evals = len(history)
    if total_evals < window_size:
        return IslandHealth(
            island_id=island_id,
            total_evaluations=total_evals,
            best_fitness=max((h["fitness"] for h in history), default=0.0),
            mean_fitness=sum(h["fitness"] for h in history) / max(total_evals, 1),
            phenotypic_entropy=1.0,
            is_plateaued=False,
            stagnation_generations=0,
            suggested_action="NOMINAL"
        )

    # Windowed fitness progress
    window = history[-window_size:]
    fitness_values = [h["fitness"] for h in window]
    min_fit = min(fitness_values)
    max_fit = max(fitness_values)
    fitness_delta = max_fit - min_fit

    # Phenotypic diversity over the window
    signatures = [h.get("phenotype_signature", "unknown") for h in window]
    entropy = calculate_phenotypic_entropy(signatures)

    is_stagnant = fitness_delta < epsilon
    entropy_collapsed = entropy < entropy_threshold

    # Count unbroken stagnation length
    all_best = [h["fitness"] for h in history]
    stagnation_count = 0
    current_best = all_best[-1]
    for past_score in reversed(all_best[:-1]):
        if abs(current_best - past_score) < epsilon:
            stagnation_count += 1
        else:
            break

    # Determine recommended supervisory intervention
    if stagnation_count > window_size * 2 and entropy_collapsed:
        action = "CATACLYSMIC_RESTART"
    elif is_stagnant or entropy_collapsed:
        action = "RING_MIGRATION"
    else:
        action = "NOMINAL"

    return IslandHealth(
        island_id=island_id,
        total_evaluations=total_evals,
        best_fitness=max(all_best),
        mean_fitness=sum(fitness_values) / len(fitness_values),
        phenotypic_entropy=entropy,
        is_plateaued=is_stagnant or entropy_collapsed,
        stagnation_generations=stagnation_count,
        suggested_action=action
    )
