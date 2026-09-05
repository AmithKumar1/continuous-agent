import pytest
from agent.ast_cache import canonicalize_expr, compute_ast_hash, ASTEvaluationCache

def test_ast_canonicalization_variable_renaming():
    code1 = """
def priority(item: float, bin_capacity: float) -> float:
    return 100.0 / (bin_capacity - item + 0.001)
"""
    code2 = """
def priority(x: float, c: float) -> float:
    return 100.0 / (c - x + 0.001)
"""
    canon1 = canonicalize_expr(code1)
    canon2 = canonicalize_expr(code2)

    assert "c" in canon1 and "i" in canon1
    assert canon1 == canon2
    assert compute_ast_hash(code1) == compute_ast_hash(code2)

def test_ast_cache_memoization(tmp_path):
    db_file = str(tmp_path / "test_cache.db")
    cache = ASTEvaluationCache(db_path=db_file)

    code = "def priority(item, bin_capacity): return 1.0 / (bin_capacity - item + 0.1)"
    assert cache.get(code) is None

    cache.put(code, fitness=0.925, diagnostic={"origin": None, "detail": "Test"})
    res = cache.get(code)
    assert res is not None
    fitness, diag = res
    assert fitness == pytest.approx(0.925)
    assert diag["detail"] == "Test"
