import pytest
from agent.staged_pipeline import StagedEvaluationPipeline
from agent.diagnostics import FailureOrigin
from agent.ast_cache import ast_cache
from problem import get_benchmark_dataset

@pytest.fixture(autouse=True)
def reset_cache():
    ast_cache.clear(clear_db=True)
    yield
    ast_cache.clear(clear_db=True)

def test_staged_pipeline_security_rejection():
    pipeline = StagedEvaluationPipeline()
    code = "import os\ndef priority(item, bin_capacity): return 1.0"
    seqs = [[10.0, 20.0]]
    diag = pipeline.evaluate(code, seqs)

    assert not diag.success
    assert diag.origin == FailureOrigin.AST_SECURITY_REJECTED

def test_staged_pipeline_z3_refutation():
    pipeline = StagedEvaluationPipeline()
    # Singularity division by zero
    code = "def priority(item: float, bin_capacity: float) -> float:\n    return 1.0 / (bin_capacity - item)"
    seqs = [[10.0, 20.0]]
    diag = pipeline.evaluate(code, seqs)

    assert not diag.success
    assert diag.origin == FailureOrigin.Z3_REFUTED
    assert "Singularity" in diag.detail

def test_staged_pipeline_sound_success():
    pipeline = StagedEvaluationPipeline()
    code = "def priority(item: float, bin_capacity: float) -> float:\n    return 100.0 / (bin_capacity - item + 0.001)"
    seqs = get_benchmark_dataset()
    diag = pipeline.evaluate(code, seqs)

    assert diag.success
    assert diag.fitness > 0.5
    assert diag.canonical_hash != ""

def test_staged_pipeline_memoized_cache_hit():
    pipeline = StagedEvaluationPipeline()
    code = "def priority(item: float, bin_capacity: float) -> float:\n    return 50.0 / (bin_capacity - item + 0.005)"
    seqs = get_benchmark_dataset()

    diag1 = pipeline.evaluate(code, seqs)
    diag2 = pipeline.evaluate(code, seqs)

    assert diag1.success and diag2.success
    assert "Cache hit" in diag2.detail
    assert diag2.fitness == pytest.approx(diag1.fitness)
