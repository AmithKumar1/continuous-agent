# tests/test_audit_logger.py
import json
import pytest
import aiosqlite
from pathlib import Path
from agent.db import init_db, get_db
from agent.adaptive_sampling import SamplingPolicy
from agent.audit_logger import record_policy_transition, record_beam_evaluation

@pytest.fixture
async def audit_test_db(tmp_path: Path):
    db_file = tmp_path / "test_audit.db"
    await init_db(str(db_file))
    return str(db_file)

@pytest.mark.asyncio
async def test_record_policy_transition(audit_test_db, monkeypatch):
    monkeypatch.setattr("agent.audit_logger.get_db", lambda: get_db(audit_test_db))

    old_policy = SamplingPolicy(temperature=0.20, top_p=0.70, beam_width=1)
    new_policy = SamplingPolicy(temperature=0.75, top_p=0.92, beam_width=3)

    await record_policy_transition(
        island_id=1,
        entropy=0.352,
        old_policy=old_policy,
        new_policy=new_policy,
        details={"reason": "entropy_dip"}
    )

    async with get_db(audit_test_db) as db:
        cursor = await db.execute("SELECT * FROM supervisor_policy_audit WHERE event_type = 'POLICY_TRANSITION';")
        row = await cursor.fetchone()

    assert row is not None
    assert row["island_id"] == 1
    assert row["temperature"] == 0.75
    assert row["top_p"] == 0.92
    assert row["beam_width"] == 3
    assert row["candidates_generated"] is None

    details = json.loads(row["details"])
    assert details["previous_temperature"] == 0.20
    assert details["reason"] == "entropy_dip"

@pytest.mark.asyncio
async def test_record_beam_evaluation(audit_test_db, monkeypatch):
    monkeypatch.setattr("agent.audit_logger.get_db", lambda: get_db(audit_test_db))

    active_policy = SamplingPolicy(temperature=0.80, top_p=0.95, beam_width=4)

    await record_beam_evaluation(
        island_id=2,
        entropy=0.28,
        policy=active_policy,
        candidates_generated=4,
        candidates_accepted=3,
        details={"rejections": ["ast_disallowed_call"]}
    )

    async with get_db(audit_test_db) as db:
        cursor = await db.execute("SELECT * FROM supervisor_policy_audit WHERE event_type = 'BEAM_EVALUATION';")
        row = await cursor.fetchone()

    assert row is not None
    assert row["island_id"] == 2
    assert row["beam_width"] == 4
    assert row["candidates_generated"] == 4
    assert row["candidates_accepted"] == 3

    meta = json.loads(row["details"])
    assert meta["rejections"] == ["ast_disallowed_call"]
