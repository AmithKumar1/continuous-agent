import aiosqlite
import logging
from typing import List, Dict, Any, Optional
from agent.vector_memory import ChromaEpisodicStore

logger = logging.getLogger("Migrations")

async def backfill_vector_store(db_path: str = "agent_state.db", vector_store: Optional[ChromaEpisodicStore] = None):
    store = vector_store or ChromaEpisodicStore()
    indexed_ids = await store.get_indexed_ids()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, start_iteration, end_iteration, dense_summary FROM episodic_summaries ORDER BY id ASC") as c:
            all_milestones = [dict(r) for r in await c.fetchall()]

    missing = [m for m in all_milestones if str(m["id"]) not in indexed_ids]
    if not missing:
        logger.info("Vector index is up-to-date. No backfill needed.")
        return

    logger.info(f"Backfill migration: Indexing {len(missing)} unindexed milestones into ChromaDB...")
    chunk_size = 50
    for i in range(0, len(missing), chunk_size):
        chunk = missing[i:i + chunk_size]
        await store.batch_index_milestones(chunk)

    logger.info("Backfill migration completed successfully.")
