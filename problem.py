import random
from typing import List, Tuple

PROGRAM_SKELETON = '''
def priority(item: float, bin_capacity: float) -> float:
    """Computes priority of placing item into a bin with given remaining capacity."""
'''

INITIAL_HEURISTIC = """
def priority(item: float, bin_capacity: float) -> float:
    # Baseline First-Fit heuristic
    return 1.0
""".strip()

def run_simulation(priority_fn, sequences: List[List[float]], bin_size: float = 100.0) -> float:
    """Evaluates heuristic across multiple bin-packing item streams."""
    total_bins_used = 0
    total_items_volume = 0.0

    for seq in sequences:
        bins = []  # Remaining capacity in each active bin
        total_items_volume += sum(seq)

        for item in seq:
            best_bin_idx = -1
            max_score = -float("inf")

            for idx, cap in enumerate(bins):
                if cap >= item:
                    try:
                        score = float(priority_fn(item, cap))
                    except Exception:
                        score = -1e9
                    if score > max_score:
                        max_score = score
                        best_bin_idx = idx

            if best_bin_idx != -1:
                bins[best_bin_idx] -= item
            else:
                bins.append(bin_size - item)

        total_bins_used += len(bins)

    if total_bins_used == 0:
        return 0.0

    efficiency = total_items_volume / (total_bins_used * bin_size)
    return max(0.0, min(1.0, efficiency))

def get_benchmark_dataset() -> List[List[float]]:
    random.seed(42)
    return [
        [round(random.uniform(5.0, 50.0), 1) for _ in range(60)]
        for _ in range(8)
    ]
