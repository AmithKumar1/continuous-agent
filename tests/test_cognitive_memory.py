import os
import tempfile
import pytest
aiosqlite = pytest.importorskip("aiosqlite")
from agent.cognitive_memory import CognitiveMemoryStore

@pytest.mark.asyncio
async def test_core_memory_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_agent.db")
        store = CognitiveMemoryStore(db_path=db_path)

        # 1. Update facts
        await store.update_core_memory("target_framework", "Lean4")
        await store.update_core_memory("max_depth", "5")

        core = await store.get_core_memory()
        assert core["target_framework"] == "Lean4"
        assert core["max_depth"] == "5"

        # 2. Delete fact
        await store.delete_core_memory("max_depth")
        core_after = await store.get_core_memory()
        assert "max_depth" not in core_after
        assert core_after["target_framework"] == "Lean4"

@pytest.mark.asyncio
async def test_heuristics_recording():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_agent.db")
        store = CognitiveMemoryStore(db_path=db_path)

        await store.record_heuristic(
            category="Arithmetic",
            condition="Division by capacity difference",
            actionable_lesson="Always guard denominators with max(..., eps)"
        )

        heuristics = await store.get_active_heuristics()
        assert len(heuristics) >= 1
        assert heuristics[0]["category"] == "Arithmetic"
        assert "guard denominators" in heuristics[0]["actionable_lesson"]
