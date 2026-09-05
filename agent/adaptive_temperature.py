# agent/adaptive_temperature.py
from dataclasses import dataclass

@dataclass(frozen=True)
class TemperatureConfig:
    t_min: float = 0.20
    t_max: float = 0.95
    h_target: float = 0.80
    gamma: float = 1.50

def calculate_adaptive_temperature(
    entropy: float,
    config: TemperatureConfig = TemperatureConfig()
) -> float:
    """
    Computes an inverse temperature based on phenotypic Shannon entropy.
    High entropy (H >= h_target) -> t_min (focused exploitation)
    Zero entropy (H = 0.0)       -> t_max (radical stochastic exploration)
    """
    if entropy >= config.h_target:
        return config.t_min

    normalized_deficit = max(0.0, 1.0 - (entropy / config.h_target))
    boost = (config.t_max - config.t_min) * (normalized_deficit ** config.gamma)
    temp = config.t_min + boost

    return round(min(max(temp, config.t_min), config.t_max), 3)
