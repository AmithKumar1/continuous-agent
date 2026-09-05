# agent/adaptive_sampling.py
from dataclasses import dataclass

@dataclass(frozen=True)
class AdaptiveSamplingConfig:
    h_target: float = 0.80
    # Temperature
    t_min: float = 0.20
    t_max: float = 0.95
    gamma_t: float = 1.50
    # Nucleus Sampling (top_p)
    p_min: float = 0.70
    p_max: float = 0.98
    gamma_p: float = 1.20
    # Mutation Beam Width (Candidate Batch Size)
    k_min: int = 1
    k_max: int = 4
    gamma_k: float = 1.00

@dataclass(frozen=True)
class SamplingPolicy:
    temperature: float
    top_p: float
    beam_width: int

def calculate_adaptive_policy(
    entropy: float,
    config: AdaptiveSamplingConfig = AdaptiveSamplingConfig()
) -> SamplingPolicy:
    """
    Derives temperature, top_p, and mutation beam width as an inverse function
    of island phenotypic diversity entropy.
    """
    if entropy >= config.h_target:
        return SamplingPolicy(
            temperature=config.t_min,
            top_p=config.p_min,
            beam_width=config.k_min
        )

    # Calculate bounded deficit D(H) in [0, 1]
    deficit = max(0.0, min(1.0, 1.0 - (entropy / config.h_target)))

    # 1. Temperature scaling
    t_boost = (config.t_max - config.t_min) * (deficit ** config.gamma_t)
    temp = round(min(max(config.t_min + t_boost, config.t_min), config.t_max), 3)

    # 2. Nucleus top_p scaling
    p_boost = (config.p_max - config.p_min) * (deficit ** config.gamma_p)
    top_p = round(min(max(config.p_min + p_boost, config.p_min), config.p_max), 3)

    # 3. Beam width scaling (integer)
    k_boost = (config.k_max - config.k_min) * (deficit ** config.gamma_k)
    beam_width = int(round(min(max(config.k_min + k_boost, float(config.k_min)), float(config.k_max))))

    return SamplingPolicy(
        temperature=temp,
        top_p=top_p,
        beam_width=beam_width
    )
