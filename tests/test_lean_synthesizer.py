import pytest
from agent.lean_synthesizer import Lean4ProofSynthesizer

def test_lean_synthesis_basic():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    return 100.0 / ((bin_capacity - item) + 0.001)
"""
    lean_code = Lean4ProofSynthesizer.synthesize(code)
    assert "def priority" in lean_code
    assert "theorem priority" in lean_code
    assert "linarith" in lean_code

def test_lean_synthesis_singularity_free():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    return item + bin_capacity
"""
    lean_code = Lean4ProofSynthesizer.synthesize(code)
    assert "def priority" in lean_code
    assert "priority_singularity_free" in lean_code
    assert "trivial" in lean_code
