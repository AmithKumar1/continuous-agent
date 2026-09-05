import aiosqlite
import logging
from typing import Any, Dict, List, Optional
from agent.db import Database

logger = logging.getLogger("MemoryStore")

class SqliteMemoryStore:
    def __init__(self, db: Database):
        self.db_path = db.db_path

    async def increment_iteration(self) -> int:
        """Atomically increments and returns the active iteration counter."""
        query = """
        UPDATE agent_state 
        SET iteration = iteration + 1,
            last_heartbeat = unixepoch('now', 'subsec')
        WHERE id = 1
        RETURNING iteration;
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(query) as cursor:
                row = await cursor.fetchone()
                await db.commit()
                return row[0] if row else 1

    async def get_execution_context(self, log_history_limit: int = 15) -> Dict[str, Any]:
        """
        Builds the context payload needed by the LLM:
        current iteration, recent cycle summaries, and active tasks.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # 1. Fetch metadata
            async with db.execute("SELECT iteration, status FROM agent_state WHERE id = 1") as c:
                state_row = await c.fetchone()
                iteration = state_row["iteration"] if state_row else 0
                status = state_row["status"] if state_row else "UNKNOWN"

            # 2. Fetch recent execution history
            logs_query = """
            SELECT iteration, summary, created_at 
            FROM execution_logs 
            ORDER BY id DESC 
            LIMIT ?
            """
            async with db.execute(logs_query, (log_history_limit,)) as c:
                logs = [dict(row) for row in await c.fetchall()]
                logs.reverse()

            # 3. Fetch pending tasks
            tasks_query = """
            SELECT id, description 
            FROM tasks 
            WHERE status = 'PENDING' 
            ORDER BY id ASC 
            LIMIT 5
            """
            async with db.execute(tasks_query) as c:
                pending_tasks = [dict(row) for row in await c.fetchall()]

            return {
                "iteration": iteration,
                "status": status,
                "recent_history": logs,
                "pending_tasks": pending_tasks
            }

    async def record_cycle(self, iteration: int, summary: str, tool_calls_count: int = 0):
        """Inserts cycle results and prunes records older than the last 500 entries."""
        insert_query = """
        INSERT INTO execution_logs (iteration, summary, tool_calls_count)
        VALUES (?, ?, ?);
        """
        prune_query = """
        DELETE FROM execution_logs 
        WHERE id NOT IN (
            SELECT id FROM execution_logs ORDER BY id DESC LIMIT 500
        );
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(insert_query, (iteration, summary, tool_calls_count))
            await db.execute(prune_query)
            await db.commit()

    async def complete_task(self, task_id: int):
        """Marks a pending task as completed."""
        query = """
        UPDATE tasks 
        SET status = 'COMPLETED', completed_at = unixepoch('now', 'subsec')
        WHERE id = ?;
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, (task_id,))
            await db.commit()
