import pytest
aiosqlite = pytest.importorskip("aiosqlite")
from agent.hybrid_search import sanitize_fts5_query

def test_sanitize_fts5_query():
    # Normal multi-word query
    q = "binary search priority"
    res = sanitize_fts5_query(q)
    assert '"binary"* AND "search"* AND "priority"*' == res

    # Query with punctuation and special chars
    q_special = "heap-sort && Z3 prover!"
    res_special = sanitize_fts5_query(q_special)
    assert '"heap"* AND "sort"* AND "Z3"* AND "prover"*' == res_special

    # Empty query
    assert sanitize_fts5_query("   ") == '""'
