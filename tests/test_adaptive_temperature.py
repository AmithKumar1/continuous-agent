# tests/test_adaptive_temperature.py
import pytest
from agent.adaptive_temperature import (
    calculate_adaptive_temperature,
    TemperatureConfig
)

def test_nominal_entropy_produces_minimum_temperature():
    config = TemperatureConfig(t_min=0.20, t_max=0.95, h_target=0.80)
    
    # At or above target entropy, temperature must remain strictly at t_min
    assert calculate_adaptive_temperature(0.80, config) == 0.20
    assert calculate_adaptive_temperature(1.50, config) == 0.20


def test_zero_entropy_produces_maximum_temperature():
    config = TemperatureConfig(t_min=0.20, t_max=0.95, h_target=0.80)
    
    # Complete monoculture (H = 0.0) must scale to t_max
    assert calculate_adaptive_temperature(0.0, config) == 0.95


def test_monotonic_scaling_with_entropy_decay():
    config = TemperatureConfig(t_min=0.20, t_max=0.95, h_target=0.80, gamma=1.0)
    
    entropies = [0.80, 0.60, 0.40, 0.20, 0.00]
    temps = [calculate_adaptive_temperature(h, config) for h in entropies]

    # Temperatures must strictly increase as entropy collapses
    for i in range(len(temps) - 1):
        assert temps[i] < temps[i + 1]


def test_clamping_behavior():
    config = TemperatureConfig(t_min=0.20, t_max=0.95, h_target=0.80)
    
    # Negative entropy inputs or float anomalies must remain bounded within [t_min, t_max]
    assert calculate_adaptive_temperature(-0.5, config) == 0.95
    assert calculate_adaptive_temperature(10.0, config) == 0.20
