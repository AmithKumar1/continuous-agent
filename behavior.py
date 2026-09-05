import hashlib
from typing import Callable, List, Tuple

DIAGNOSTIC_PROBES = [
    [10.0, 20.0, 30.0, 40.0, 15.0, 25.0, 35.0, 5.0, 45.0, 10.0],
    [50.0, 40.0, 30.0, 20.0, 10.0, 5.0, 15.0, 25.0, 35.0, 45.0],
    [5.0] * 20,
    [30.0, 30.0, 30.0, 10.0, 10.0, 10.0, 50.0, 50.0],
]

def get_behavioral_fingerprint(
    priority_fn: Callable[[float, float], float],
    probes: List[List[float]] = DIAGNOSTIC_PROBES,
    bin_size: float = 100.0
) -> Tuple[str, bool]:
    decision_log = []

    for seq in probes:
        bins: List[float] = []

        for item in seq:
            best_idx = -1
            max_score = -float("inf")

            for idx, cap in enumerate(bins):
                if cap >= item:
                    try:
                        score = float(priority_fn(item, cap))
                    except Exception:
                        return "invalid_runtime", False

                    if score > max_score:
                        max_score = score
                        best_idx = idx

            if best_idx != -1:
                bins[best_idx] -= item
                decision_log.append(best_idx)
            else:
                bins.append(bin_size - item)
                decision_log.append(len(bins) - 1)

    signature_bytes = bytes(decision_log)
    fingerprint = hashlib.sha256(signature_bytes).hexdigest()
    return fingerprint, True
