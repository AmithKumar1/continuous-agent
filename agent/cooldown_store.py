import aiosqlite
from typing import Any, Dict, Optional
from agent.db import Database

class SqliteCooldownStore:
    def __init__(self, db: Database):
        self.db_path = db.db_path

    async def get_cooldown(self, domain: str) -> Optional[Dict[str, Any]]:
        query = """
        SELECT paused_until, tokens, last_refill, rate, capacity 
        FROM domain_cooldowns 
        WHERE domain = ?
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (domain,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_cooldown(
        self,
        domain: str,
        paused_until: float,
        tokens: float,
        last_refill: float,
        rate: float,
        capacity: float
    ):
        query = """
        INSERT INTO domain_cooldowns (domain, paused_until, tokens, last_refill, rate, capacity, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, unixepoch('now', 'subsec'))
        ON CONFLICT(domain) DO UPDATE SET
            paused_until = excluded.paused_until,
            tokens = excluded.tokens,
            last_refill = excluded.last_refill,
            rate = excluded.rate,
            capacity = excluded.capacity,
            updated_at = excluded.updated_at;
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, (domain, paused_until, tokens, last_refill, rate, capacity))
            await db.commit()

# Alias for backwards compatibility
CooldownStore = SqliteCooldownStore
