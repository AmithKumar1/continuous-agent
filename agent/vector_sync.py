import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import aiosqlite
from agent.vector_memory import ChromaEpisodicStore

logger = logging.getLogger("VectorSync")

class VectorSyncCoordinator:
    def __init__(self, db_path: str = "agent_state.db", vector_store: Optional[ChromaEpisodicStore] = None):
        self.db_path = db_path
        self.vector_store = vector_store or ChromaEpisodicStore()
        self.is_syncing = False
        self.last_sync_timestamp: Optional[str] = None
        self._lock = asyncio.Lock()

    async def get_sync_status(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM episodic_summaries") as c:
                sqlite_count = (await c.fetchone())[0]

        indexed_ids = await self.vector_store.get_indexed_ids()
        chroma_count = len(indexed_ids)
        pending_count = max(0, sqlite_count - chroma_count)

        return {
            "sqlite_milestone_count": sqlite_count,
            "chroma_document_count": chroma_count,
            "pending_sync_count": pending_count,
            "is_in_sync": pending_count == 0,
            "is_syncing": self.is_syncing,
            "last_sync": self.last_sync_timestamp
        }

    async def run_sync(self) -> Dict[str, Any]:
        async with self._lock:
            self.is_syncing = True
            try:
                from agent.migrations import backfill_vector_store
                await backfill_vector_store(self.db_path, self.vector_store)
                self.last_sync_timestamp = datetime.now(timezone.utc).isoformat()
            finally:
                self.is_syncing = False

        return await self.get_sync_status()

sync_coordinator = VectorSyncCoordinator()
