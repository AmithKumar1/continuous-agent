# tests/test_adaptive_sampling.py
import pytest
from agent.adaptive_sampling import (
    calculate_adaptive_policy,
    AdaptiveSamplingConfig
)

def test_nominal_entropy_maintains_baseline():
    cfg = AdaptiveSamplingConfig(
        h_target=0.80,
        t_min=0.20, t_max=0.95,
        p_min=0.70, p_max=0.98,
        k_min=1, k_max=4
    )
    policy = calculate_adaptive_policy(0.85, cfg)
    assert policy.temperature == 0.20
    assert policy.top_p == 0.70
    assert policy.beam_width == 1


def test_zero_entropy_expands_to_maximum_exploration():
    cfg = AdaptiveSamplingConfig(
        h_target=0.80,
        t_min=0.20, t_max=0.95,
        p_min=0.70, p_max=0.98,
        k_min=1, k_max=4
    )
    policy = calculate_adaptive_policy(0.00, cfg)
    assert policy.temperature == 0.95
    assert policy.top_p == 0.98
    assert policy.beam_width == 4


def test_intermediate_entropy_scaling():
    cfg = AdaptiveSamplingConfig(
        h_target=0.80,
        t_min=0.20, t_max=0.95,
        p_min=0.70, p_max=0.98,
        k_min=1, k_max=4,
        gamma_k=1.0  # Linear scaling for predictable beam boundaries
    )
    # Deficit at H=0.40 is (1 - 0.4/0.8) = 0.50
    # Expected beam_width = round(1 + (4 - 1) * 0.50) = round(2.5) = 2 or 3
    policy = calculate_adaptive_policy(0.40, cfg)
    assert 0.20 < policy.temperature < 0.95
    assert 0.70 < policy.top_p < 0.98
    assert policy.beam_width in (2, 3)


def test_clamped_extremes():
    cfg = AdaptiveSamplingConfig()
    # Negative entropy
    low = calculate_adaptive_policy(-1.0, cfg)
    assert low.temperature == cfg.t_max
    assert low.top_p == cfg.p_max
    assert low.beam_width == cfg.k_max

    # Very high entropy
    high = calculate_adaptive_policy(10.0, cfg)
    assert high.temperature == cfg.t_min
    assert high.top_p == cfg.p_min
    assert high.beam_width == cfg.k_min
