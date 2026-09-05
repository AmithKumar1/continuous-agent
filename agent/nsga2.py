from dataclasses import dataclass
from typing import List, Tuple
import random

@dataclass
class NSGA2Individual:
    id: str
    code: str
    packing_ratio: float  # Objective 1: Maximize
    fuel_consumed: int    # Objective 2: Minimize
    phenotype_signature: str
    rank: int = 0
    crowding_distance: float = 0.0

def dominates(p: NSGA2Individual, q: NSGA2Individual) -> bool:
    """Checks if p Pareto-dominates q (higher packing, lower or equal fuel)."""
    better_or_equal = (p.packing_ratio >= q.packing_ratio) and (p.fuel_consumed <= q.fuel_consumed)
    strictly_better = (p.packing_ratio > q.packing_ratio) or (p.fuel_consumed < q.fuel_consumed)
    return better_or_equal and strictly_better

def fast_non_dominated_sort(population: List[NSGA2Individual]) -> List[List[NSGA2Individual]]:
    """Partitions the population into Pareto fronts: F1, F2, ..., Fk."""
    if not population:
        return []

    fronts: List[List[NSGA2Individual]] = [[]]
    domination_counts = {p.id: 0 for p in population}
    dominated_sets = {p.id: [] for p in population}

    for p in population:
        for q in population:
            if dominates(p, q):
                dominated_sets[p.id].append(q)
            elif dominates(q, p):
                domination_counts[p.id] += 1

        if domination_counts[p.id] == 0:
            p.rank = 1
            fronts[0].append(p)

    i = 0
    while len(fronts[i]) > 0:
        next_front: List[NSGA2Individual] = []
        for p in fronts[i]:
            for q in dominated_sets[p.id]:
                domination_counts[q.id] -= 1
                if domination_counts[q.id] == 0:
                    q.rank = i + 2
                    next_front.append(q)
        i += 1
        fronts.append(next_front)

    if not fronts[-1]:
        fronts.pop()

    return fronts

def assign_crowding_distance(front: List[NSGA2Individual]):
    """Assigns boundary-preserving crowding distances to maintain diversity."""
    n = len(front)
    if n == 0:
        return
    if n <= 2:
        for ind in front:
            ind.crowding_distance = float("inf")
        return

    for ind in front:
        ind.crowding_distance = 0.0

    # Objective 1: Packing Ratio (Maximize)
    front.sort(key=lambda x: x.packing_ratio)
    front[0].crowding_distance = float("inf")
    front[-1].crowding_distance = float("inf")
    pack_span = front[-1].packing_ratio - front[0].packing_ratio
    if pack_span > 1e-9:
        for i in range(1, n - 1):
            front[i].crowding_distance += (
                front[i + 1].packing_ratio - front[i - 1].packing_ratio
            ) / pack_span

    # Objective 2: Fuel Consumption (Minimize)
    front.sort(key=lambda x: x.fuel_consumed)
    front[0].crowding_distance = float("inf")
    front[-1].crowding_distance = float("inf")
    fuel_span = front[-1].fuel_consumed - front[0].fuel_consumed
    if fuel_span > 0:
        for i in range(1, n - 1):
            front[i].crowding_distance += (
                front[i + 1].fuel_consumed - front[i - 1].fuel_consumed
            ) / fuel_span

def nsga2_truncate(population: List[NSGA2Individual], target_size: int) -> List[NSGA2Individual]:
    """Selects the top target_size survivors based on non-dominated rank and crowding distance."""
    if len(population) <= target_size:
        return population

    fronts = fast_non_dominated_sort(population)
    survivors: List[NSGA2Individual] = []

    for front in fronts:
        assign_crowding_distance(front)
        if len(survivors) + len(front) <= target_size:
            survivors.extend(front)
        else:
            # Sort boundary front by crowding distance descending
            remaining_slots = target_size - len(survivors)
            front.sort(key=lambda ind: ind.crowding_distance, reverse=True)
            survivors.extend(front[:remaining_slots])
            break

    return survivors

def crowded_tournament_select(
    population: List[NSGA2Individual], tournament_size: int = 2
) -> NSGA2Individual:
    """
    Selects 1 individual using the crowded comparison operator:
    Prefers lower rank; breaks ties using larger crowding distance.
    """
    candidates = random.sample(population, min(len(population), tournament_size))
    best = candidates[0]
    for candidate in candidates[1:]:
        if candidate.rank < best.rank:
            best = candidate
        elif candidate.rank == best.rank:
            if candidate.crowding_distance > best.crowding_distance:
                best = candidate
    return best
