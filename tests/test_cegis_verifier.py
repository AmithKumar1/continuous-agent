import pytest
z3 = pytest.importorskip("z3")
from cegis_verifier import SymbolicContractVerifier

def test_singularity_detection():
    verifier = SymbolicContractVerifier(timeout_ms=2000)
    # This heuristic divides by (bin_capacity - item), which hits zero when item == bin_capacity
    unsafe_code = """
def priority(item: float, bin_capacity: float) -> float:
    return item / (bin_capacity - item)
"""
    is_verified, ce = verifier.verify(unsafe_code)
    assert not is_verified
    assert ce is not None
    assert ce.invariant_name == "NoSingularity"
    assert ce.item == ce.bin_capacity

def test_sound_heuristic():
    verifier = SymbolicContractVerifier(timeout_ms=2000)
    # This heuristic avoids division by zero via safe constant offset
    safe_code = """
def priority(item: float, bin_capacity: float) -> float:
    return item / (bin_capacity + 1.0)
"""
    is_verified, ce = verifier.verify(safe_code)
    # The NoSingularity contract should hold since bin_capacity >= 0 and denominator >= 1.0
    if ce:
        assert ce.invariant_name != "NoSingularity"
