import asyncio
import re
from typing import Any, Dict, List, Optional
import aiosqlite
from agent.vector_memory import ChromaEpisodicStore

def sanitize_fts5_query(raw_query: str) -> str:
    words = re.findall(r"\w+", raw_query.strip())
    if not words:
        return '""'
    return " AND ".join(f'"{w}"*' for w in words)

class HybridEpisodicRetriever:
    def __init__(self, db_path: str = "agent_state.db", vector_store: Optional[ChromaEpisodicStore] = None):
        self.db_path = db_path
        self.vector_store = vector_store or ChromaEpisodicStore()

    async def _query_fts5(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        sanitized = sanitize_fts5_query(query)
        if sanitized == '""':
            return []

        sql = """
        SELECT 
            e.id,
            e.start_iteration,
            e.end_iteration,
            e.dense_summary,
            datetime(e.created_at, 'unixepoch', 'localtime') AS created_at,
            bm25(episodic_summaries_fts) AS rank_score
        FROM episodic_summaries_fts f
        JOIN episodic_summaries e ON f.rowid = e.id
        WHERE episodic_summaries_fts MATCH ?
        ORDER BY rank_score ASC
        LIMIT ?;
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                async with db.execute(sql, (sanitized, limit)) as cursor:
                    return [dict(r) for r in await cursor.fetchall()]
            except Exception:
                return []

    async def _query_vector(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        try:
            return await self.vector_store.query_similar(query, limit=limit)
        except Exception:
            return []

    async def search(self, query: str, top_k: int = 5, rrf_k: int = 60) -> List[Dict[str, Any]]:
        fts_results, vector_results = await asyncio.gather(
            self._query_fts5(query, limit=top_k * 4),
            self._query_vector(query, limit=top_k * 4)
        )

        rrf_scores: Dict[int, float] = {}
        doc_map: Dict[int, Dict[str, Any]] = {}
        matched_by: Dict[int, List[str]] = {}

        for rank, item in enumerate(fts_results, start=1):
            doc_id = item["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))
            doc_map[doc_id] = item
            matched_by.setdefault(doc_id, []).append("KEYWORD (FTS5)")

        for rank, item in enumerate(vector_results, start=1):
            doc_id = item["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))
            if doc_id not in doc_map:
                doc_map[doc_id] = item
            matched_by.setdefault(doc_id, []).append("SEMANTIC (ChromaDB)")

        sorted_ids = sorted(rrf_scores.keys(), key=lambda did: rrf_scores[did], reverse=True)

        final_results = []
        for did in sorted_ids[:top_k]:
            doc = doc_map[did]
            final_results.append({
                "id": did,
                "start_iteration": doc["start_iteration"],
                "end_iteration": doc["end_iteration"],
                "dense_summary": doc["dense_summary"],
                "rrf_score": round(rrf_scores[did], 5),
                "matched_sources": matched_by[did]
            })

        return final_results
