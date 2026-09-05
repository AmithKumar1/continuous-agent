import pytest
from behavior import get_behavioral_fingerprint, compute_behavioral_distance

def test_fingerprint_generation():
    def simple_priority(item: float, bin_capacity: float) -> float:
        return item / max(bin_capacity, 0.001)

    fp, ok = get_behavioral_fingerprint(simple_priority)
    assert ok is True
    assert len(fp) > 0

    # Distance to itself must be zero
    dist = compute_behavioral_distance(fp, fp)
    assert dist == 0.0

def test_fingerprint_differentiation():
    def fn_a(item: float, bin_capacity: float) -> float:
        return item

    def fn_b(item: float, bin_capacity: float) -> float:
        return bin_capacity - item

    fp_a, ok_a = get_behavioral_fingerprint(fn_a)
    fp_b, ok_b = get_behavioral_fingerprint(fn_b)

    assert ok_a and ok_b
    dist = compute_behavioral_distance(fp_a, fp_b)
    assert dist > 0.0
