import pytest
from agent.nsga2 import (
    NSGA2Individual,
    dominates,
    fast_non_dominated_sort,
    assign_crowding_distance,
    nsga2_truncate,
    crowded_tournament_select
)

def test_dominance_criteria():
    a = NSGA2Individual("a", "...", packing_ratio=0.95, fuel_consumed=500, phenotype_signature="s1")
    b = NSGA2Individual("b", "...", packing_ratio=0.90, fuel_consumed=800, phenotype_signature="s2")
    c = NSGA2Individual("c", "...", packing_ratio=0.95, fuel_consumed=800, phenotype_signature="s3")

    assert dominates(a, b) is True
    assert dominates(b, a) is False
    assert dominates(a, c) is True
    assert dominates(c, a) is False

def test_fast_non_dominated_sort_fronts():
    # Frontier 1: p1 (0.95, 400), p2 (0.98, 1200)
    # Frontier 2: p3 (0.92, 600), p4 (0.95, 1400)
    p1 = NSGA2Individual("p1", "...", 0.95, 400, "sig")
    p2 = NSGA2Individual("p2", "...", 0.98, 1200, "sig")
    p3 = NSGA2Individual("p3", "...", 0.92, 600, "sig")
    p4 = NSGA2Individual("p4", "...", 0.95, 1400, "sig")

    fronts = fast_non_dominated_sort([p1, p2, p3, p4])
    assert len(fronts) == 2
    assert {ind.id for ind in fronts[0]} == {"p1", "p2"}
    assert {ind.id for ind in fronts[1]} == {"p3", "p4"}
    assert p1.rank == 1 and p2.rank == 1
    assert p3.rank == 2 and p4.rank == 2

def test_crowding_distance_boundary_assignment():
    p1 = NSGA2Individual("p1", "...", 0.90, 300, "sig")
    p2 = NSGA2Individual("p2", "...", 0.93, 600, "sig")
    p3 = NSGA2Individual("p3", "...", 0.96, 900, "sig")

    assign_crowding_distance([p1, p2, p3])
    # Boundary solutions in objective space must receive infinite distance
    assert p1.crowding_distance == float("inf")
    assert p3.crowding_distance == float("inf")
    assert 0 < p2.crowding_distance < float("inf")

def test_nsga2_truncate_preserves_diversity():
    # 4 individuals, truncate to 3
    # Front 1 contains 2 points (must be kept)
    # Front 2 contains 2 points: one on boundary (inf distance), one interior
    p1 = NSGA2Individual("p1", "...", 0.98, 400, "sig")
    p2 = NSGA2Individual("p2", "...", 0.96, 300, "sig")
    p3_bound = NSGA2Individual("p3", "...", 0.90, 200, "sig")
    p4_mid = NSGA2Individual("p4", "...", 0.92, 500, "sig")

    survivors = nsga2_truncate([p1, p2, p3_bound, p4_mid], target_size=3)
    survivor_ids = {s.id for s in survivors}

    assert len(survivors) == 3
    assert "p1" in survivor_ids
    assert "p2" in survivor_ids
    assert "p3" in survivor_ids  # Boundary point prioritized over interior p4

def test_crowded_tournament_select():
    # Rank 1 must beat Rank 2
    p1 = NSGA2Individual("p1", "...", 0.95, 400, "sig", rank=1, crowding_distance=1.0)
    p2 = NSGA2Individual("p2", "...", 0.90, 600, "sig", rank=2, crowding_distance=5.0)
    winner = crowded_tournament_select([p1, p2], tournament_size=2)
    assert winner.id == "p1"

    # Same rank -> higher crowding distance wins
    p3 = NSGA2Individual("p3", "...", 0.95, 400, "sig", rank=1, crowding_distance=10.0)
    winner2 = crowded_tournament_select([p1, p3], tournament_size=2)
    assert winner2.id == "p3"
