import pytest
from sandbox import evaluate_heuristic_dual

def test_heuristic_dual_evaluation():
    # Deterministic priority heuristic
    code = """
def priority(item: float, bin_capacity: float) -> float:
    return item / max(bin_capacity, 0.001)
"""
    sequences = [
        [10.0, 20.0, 30.0],
        [50.0, 50.0],
        [5.0, 15.0, 25.0, 35.0]
    ]

    ok, fitness, err = evaluate_heuristic_dual(code, sequences, timeout_sec=3.0)
    assert ok is True
    assert 0.0 <= fitness <= 1.0
    assert err == ""

def test_heuristic_dual_syntax_error():
    broken_code = "def priority(x, y: return x +"
    sequences = [[10.0, 20.0]]
    ok, fitness, err = evaluate_heuristic_dual(broken_code, sequences)
    assert ok is False
    assert fitness == -1.0
