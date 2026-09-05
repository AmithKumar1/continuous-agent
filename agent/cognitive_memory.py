import aiosqlite
import logging
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger("CognitiveMemory")

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS core_memory (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

CREATE TABLE IF NOT EXISTS learned_heuristics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    condition TEXT NOT NULL,
    actionable_lesson TEXT NOT NULL,
    times_applied INTEGER DEFAULT 1,
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);
CREATE INDEX IF NOT EXISTS idx_heuristics_cat ON learned_heuristics(category);

CREATE TABLE IF NOT EXISTS episodic_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_iteration INTEGER NOT NULL,
    end_iteration INTEGER NOT NULL,
    dense_summary TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration INTEGER NOT NULL,
    summary TEXT NOT NULL,
    tool_calls_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);
"""

class CognitiveMemoryStore:
    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path
        self.client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.compaction_threshold = 12
        self._initialized = False

    async def _ensure_schema(self, db: aiosqlite.Connection):
        if not self._initialized:
            await db.executescript(MEMORY_SCHEMA)
            await db.commit()
            self._initialized = True

    async def get_core_memory(self) -> Dict[str, str]:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT key, value FROM core_memory") as c:
                return {row["key"]: row["value"] for row in await c.fetchall()}

    async def update_core_memory(self, key: str, value: str):
        query = """
        INSERT INTO core_memory (key, value, updated_at)
        VALUES (?, ?, unixepoch('now', 'subsec'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at;
        """
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.execute(query, (key, value))
            await db.commit()

    async def delete_core_memory(self, key: str):
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.execute("DELETE FROM core_memory WHERE key = ?", (key,))
            await db.commit()

    async def get_active_heuristics(self, limit: int = 10) -> List[Dict[str, Any]]:
        query = """
        SELECT id, category, condition, actionable_lesson, times_applied 
        FROM learned_heuristics 
        ORDER BY times_applied DESC, id DESC 
        LIMIT ?
        """
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (limit,)) as c:
                return [dict(r) for r in await c.fetchall()]

    async def record_heuristic(self, category: str, condition: str, actionable_lesson: str):
        query = """
        INSERT INTO learned_heuristics (category, condition, actionable_lesson)
        VALUES (?, ?, ?);
        """
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.execute(query, (category, condition, actionable_lesson))
            await db.commit()

    async def delete_heuristic(self, heuristic_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.execute("DELETE FROM learned_heuristics WHERE id = ?", (heuristic_id,))
            await db.commit()

    async def get_prompt_context(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT dense_summary FROM episodic_summaries ORDER BY id DESC LIMIT 1") as c:
                row = await c.fetchone()
                macro_history = row["dense_summary"] if row else "No prior history consolidated yet."

            async with db.execute("SELECT iteration, summary FROM execution_logs ORDER BY id DESC LIMIT 3") as c:
                raw_recent = [dict(r) for r in await c.fetchall()]
                raw_recent.reverse()

        core_mem = await self.get_core_memory()
        heuristics = await self.get_active_heuristics()

        return {
            "core_memory": core_mem,
            "learned_rules": heuristics,
            "historical_macro_context": macro_history,
            "recent_immediate_cycles": raw_recent
        }

    async def maybe_compact(self):
        if not self.client:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT COALESCE(MAX(end_iteration), 0) FROM episodic_summaries") as c:
                last_compacted_iter = (await c.fetchone())[0]

            count_query = "SELECT COUNT(*) FROM execution_logs WHERE iteration > ?"
            async with db.execute(count_query, (last_compacted_iter,)) as c:
                uncompacted_count = (await c.fetchone())[0]

            if uncompacted_count < self.compaction_threshold:
                return

            query = "SELECT iteration, summary FROM execution_logs WHERE iteration > ? ORDER BY iteration ASC"
            async with db.execute(query, (last_compacted_iter,)) as c:
                logs_to_compress = [dict(r) for r in await c.fetchall()]

            async with db.execute("SELECT dense_summary FROM episodic_summaries ORDER BY id DESC LIMIT 1") as c:
                row = await c.fetchone()
                prior_summary = row["dense_summary"] if row else "None"

        compaction_prompt = (
            f"Prior Executive Summary:\n{prior_summary}\n\n"
            f"New Raw Execution Logs to Integrate:\n{logs_to_compress}\n\n"
            "Produce an updated, ultra-dense executive summary. "
            "Preserve: critical decisions, permanent changes, identified constraints, and recurring failures. "
            "Discard: redundant routine checks, timestamp noise. Keep under 250 words."
        )

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a memory consolidation engine. Compact events into dense factual statements."},
                {"role": "user", "content": compaction_prompt}
            ],
            max_tokens=400,
            temperature=0.2
        )

        new_summary = response.choices[0].message.content
        start_iter = logs_to_compress[0]["iteration"]
        end_iter = logs_to_compress[-1]["iteration"]

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            cursor = await db.execute(
                "INSERT INTO episodic_summaries (start_iteration, end_iteration, dense_summary) VALUES (?, ?, ?)",
                (start_iter, end_iter, new_summary)
            )
            summary_id = cursor.lastrowid
            await db.commit()

        # Attempt to synchronize with vector store
        try:
            from agent.vector_memory import ChromaEpisodicStore
            vector_store = ChromaEpisodicStore()
            await vector_store.index_milestone(summary_id, start_iter, end_iter, new_summary)
        except Exception as e:
            logger.warning(f"Vector memory sync deferred: {e}")

        logger.info(f"Memory compacted successfully for cycles #{start_iter} - #{end_iter}.")
