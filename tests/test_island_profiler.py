import math
import pytest
from agent.island_profiler import (
    HeuristicPoint,
    IslandHealth,
    compute_pareto_frontier,
    calculate_phenotypic_entropy,
    profile_island,
)

# ---------------------------------------------------------------------------
# 1. 2D Pareto Dominance Tests
# ---------------------------------------------------------------------------

def test_compute_pareto_frontier_empty():
    """Empty candidate pool returns an empty frontier."""
    assert compute_pareto_frontier([]) == []


def test_compute_pareto_frontier_single_point():
    """A solitary point is unconditionally Pareto-optimal."""
    point = HeuristicPoint(
        id="h0", island_id=0, code="return 1.0",
        packing_ratio=0.88, fuel_consumed=500,
        generation=1, phenotype_signature="sig_a"
    )
    frontier = compute_pareto_frontier([point])
    assert len(frontier) == 1
    assert frontier[0].id == "h0"
    assert frontier[0].is_pareto is True


def test_compute_pareto_frontier_strict_dominance():
    """
    Candidate A (fuel: 600, pack: 0.94) strictly dominates Candidate B (fuel: 900, pack: 0.91).
    B uses more fuel AND yields worse packing efficiency.
    """
    dominant = HeuristicPoint(
        id="dom", island_id=0, code="...",
        packing_ratio=0.94, fuel_consumed=600,
        generation=2, phenotype_signature="sig_a"
    )
    dominated = HeuristicPoint(
        id="sub", island_id=0, code="...",
        packing_ratio=0.91, fuel_consumed=900,
        generation=2, phenotype_signature="sig_b"
    )

    frontier = compute_pareto_frontier([dominated, dominant])
    assert len(frontier) == 1
    assert frontier[0].id == "dom"
    assert dominant.is_pareto is True
    assert dominated.is_pareto is False


def test_compute_pareto_frontier_tradeoff():
    """
    Tests valid trade-offs along the curve:
    Fast algorithm (low fuel, moderate pack) vs Slow algorithm (high fuel, high pack).
    Both must coexist on the frontier.
    """
    fast = HeuristicPoint(
        id="fast", island_id=0, code="...",
        packing_ratio=0.89, fuel_consumed=400,
        generation=1, phenotype_signature="sig_fast"
    )
    balanced = HeuristicPoint(
        id="balanced", island_id=1, code="...",
        packing_ratio=0.93, fuel_consumed=850,
        generation=3, phenotype_signature="sig_mid"
    )
    heavy = HeuristicPoint(
        id="heavy", island_id=2, code="...",
        packing_ratio=0.97, fuel_consumed=1800,
        generation=5, phenotype_signature="sig_slow"
    )
    suboptimal = HeuristicPoint(
        id="bad", island_id=0, code="...",
        packing_ratio=0.90, fuel_consumed=1200,
        generation=4, phenotype_signature="sig_bad"
    )

    frontier = compute_pareto_frontier([fast, balanced, heavy, suboptimal])
    frontier_ids = [p.id for p in frontier]

    assert frontier_ids == ["fast", "balanced", "heavy"]
    assert suboptimal.is_pareto is False


def test_compute_pareto_frontier_tie_handling():
    """When two algorithms share identical fuel costs, the higher packing ratio wins."""
    cheap_worse = HeuristicPoint(
        id="tie_worse", island_id=0, code="...",
        packing_ratio=0.85, fuel_consumed=500,
        generation=1, phenotype_signature="sig_1"
    )
    cheap_better = HeuristicPoint(
        id="tie_better", island_id=0, code="...",
        packing_ratio=0.92, fuel_consumed=500,
        generation=1, phenotype_signature="sig_2"
    )

    frontier = compute_pareto_frontier([cheap_worse, cheap_better])
    assert len(frontier) == 1
    assert frontier[0].id == "tie_better"
    assert cheap_better.is_pareto is True
    assert cheap_worse.is_pareto is False


# ---------------------------------------------------------------------------
# 2. Shannon Phenotypic Entropy Tests
# ---------------------------------------------------------------------------

def test_calculate_phenotypic_entropy_empty():
    """Zero signatures produce zero entropy."""
    assert calculate_phenotypic_entropy([]) == 0.0


def test_calculate_phenotypic_entropy_zero_diversity():
    """Monolithic populations (all individuals share one phenotype) produce H = 0.0."""
    signatures = ["uniform_strategy"] * 50
    assert calculate_phenotypic_entropy(signatures) == pytest.approx(0.0)


def test_calculate_phenotypic_entropy_uniform_distribution():
    """
    Uniform distribution across 4 discrete clusters yields exactly log2(4) = 2.0 bits.
    """
    signatures = ["cluster_0", "cluster_1", "cluster_2", "cluster_3"] * 25
    expected_entropy = math.log2(4)
    assert calculate_phenotypic_entropy(signatures) == pytest.approx(expected_entropy, rel=1e-5)


def test_calculate_phenotypic_entropy_skewed():
    """
    Binary split with 50/50 distribution yields -2 * (0.5 * log2(0.5)) = 1.0 bit.
    """
    signatures = ["cluster_A"] * 20 + ["cluster_B"] * 20
    assert calculate_phenotypic_entropy(signatures) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. Island Health & Plateau Trigger Rules
# ---------------------------------------------------------------------------

def test_profile_island_insufficient_history():
    """Populations below the sliding window size remain in NOMINAL state."""
    history = [
        {"fitness": 0.85, "phenotype_signature": "sig_a"},
        {"fitness": 0.86, "phenotype_signature": "sig_b"},
    ]
    health = profile_island(island_id=0, history=history, window_size=10)

    assert health.is_plateaued is False
    assert health.suggested_action == "NOMINAL"
    assert health.best_fitness == 0.86
    assert health.total_evaluations == 2


def test_profile_island_healthy_progression():
    """Active improvements with steady entropy yield NOMINAL status."""
    # Gradual fitness climb from 0.80 to 0.95 across 25 evaluations with 5 diverse clusters
    history = [
        {
            "fitness": 0.80 + (i * 0.006),
            "phenotype_signature": f"cluster_{i % 5}"
        }
        for i in range(25)
    ]
    health = profile_island(island_id=1, history=history, window_size=15, epsilon=0.001)

    assert health.is_plateaued is False
    assert health.suggested_action == "NOMINAL"
    assert health.stagnation_generations == 0
    assert health.phenotypic_entropy > 1.5


def test_profile_island_triggers_ring_migration_on_fitness_plateau():
    """
    Detects flatlined fitness velocity over the window and triggers RING_MIGRATION
    when stagnation count is under the cataclysmic restart limit.
    """
    window_size = 15
    # 20 generations of identical fitness (0.9150), but with moderate cluster diversity
    history = [
        {
            "fitness": 0.9150,
            "phenotype_signature": f"cluster_{i % 3}"
        }
        for i in range(20)
    ]
    health = profile_island(
        island_id=2,
        history=history,
        window_size=window_size,
        epsilon=0.0005,
        entropy_threshold=0.5
    )

    assert health.is_plateaued is True
    assert health.suggested_action == "RING_MIGRATION"
    assert health.stagnation_generations == 19


def test_profile_island_triggers_ring_migration_on_diversity_collapse():
    """
    Detects phenotypic entropy drop below threshold (< 0.6) despite subtle fitness noise.
    """
    window_size = 10
    # Noise exceeds epsilon, but all 15 entries have collapsed to a single phenotype
    history = [
        {
            "fitness": 0.88 + (0.002 * (i % 2)),
            "phenotype_signature": "monolithic_cluster"
        }
        for i in range(15)
    ]
    health = profile_island(
        island_id=3,
        history=history,
        window_size=window_size,
        epsilon=0.0005,
        entropy_threshold=0.6
    )

    assert health.phenotypic_entropy == pytest.approx(0.0)
    assert health.is_plateaued is True
    assert health.suggested_action == "RING_MIGRATION"


def test_profile_island_triggers_cataclysmic_restart():
    """
    Severe stagnation: prolonged lack of improvement (> window_size * 2) combined
    with collapsed phenotypic entropy triggers a CATACLYSMIC_RESTART.
    """
    window_size = 10
    total_evals = 35  # Stagnation length: 34 (greater than window_size * 2 = 20)

    history = [
        {
            "fitness": 0.9200,
            "phenotype_signature": "frozen_cluster"
        }
        for _ in range(total_evals)
    ]

    health = profile_island(
        island_id=0,
        history=history,
        window_size=window_size,
        epsilon=0.0001,
        entropy_threshold=0.5
    )

    assert health.is_plateaued is True
    assert health.stagnation_generations > (window_size * 2)
    assert health.phenotypic_entropy == pytest.approx(0.0)
    assert health.suggested_action == "CATACLYSMIC_RESTART"
