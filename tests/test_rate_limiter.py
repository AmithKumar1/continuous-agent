import os
import tempfile
import pytest
aiosqlite = pytest.importorskip("aiosqlite")
from agent.db import Database
from agent.cooldown_store import SqliteCooldownStore
from agent.rate_limiter import DomainRateLimiter

@pytest.mark.asyncio
async def test_rate_limiter_domain_tokens():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_agent.db")
        db = Database(db_path=db_path)
        await db.init_schema()

        store = SqliteCooldownStore(db)
        limiter = DomainRateLimiter(store, default_rpm=60, default_tpm=10000)

        # First request should be permitted
        can_proceed, wait_time = await limiter.check_and_consume("api.openai.com", tokens=500)
        assert can_proceed is True
        assert wait_time == 0.0

        # Excessive tokens over TPM
        can_proceed_huge, wait_time_huge = await limiter.check_and_consume("api.openai.com", tokens=20000)
        assert can_proceed_huge is False
        assert wait_time_huge > 0.0
