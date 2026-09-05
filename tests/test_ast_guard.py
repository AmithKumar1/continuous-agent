import pytest
from agent.ast_guard import sanitize_ast, SecurityError

def test_ast_guard_valid_math():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    gap = bin_capacity - item
    return 100.0 / (gap + 0.001)
"""
    # Should not raise
    sanitize_ast(code)

def test_ast_guard_conditional_expression():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    return 100.0 if (bin_capacity - item) < 0.1 else 1.0 / (bin_capacity - item + 0.01)
"""
    # Should not raise
    sanitize_ast(code)

def test_ast_guard_reject_import():
    code = """
import os
def priority(item: float, bin_capacity: float) -> float:
    return 1.0
"""
    with pytest.raises(SecurityError) as exc:
        sanitize_ast(code)
    assert "Unsafe AST element rejected: Import" in str(exc.value)

def test_ast_guard_reject_dunder_access():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    return item.__class__.__name__
"""
    with pytest.raises(SecurityError) as exc:
        sanitize_ast(code)
    assert "rejected" in str(exc.value).lower() or "forbidden" in str(exc.value).lower()

def test_ast_guard_reject_system_calls():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    eval("print('escape')")
    return 1.0
"""
    with pytest.raises(SecurityError):
        sanitize_ast(code)

def test_ast_guard_reject_loops():
    code = """
def priority(item: float, bin_capacity: float) -> float:
    total = 0.0
    for i in range(10):
        total += i
    return total
"""
    with pytest.raises(SecurityError):
        sanitize_ast(code)
