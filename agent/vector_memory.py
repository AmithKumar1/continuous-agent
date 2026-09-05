import asyncio
import logging
from typing import Any, Dict, List, Set, Optional
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger("VectorMemory")

class ChromaEpisodicStore:
    def __init__(self, persist_dir: str = "./chroma_data"):
        self.openai_client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.persist_dir = persist_dir
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            from chromadb.config import Settings
            chroma_client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = chroma_client.get_or_create_collection(
                name="episodic_milestones",
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    async def get_embedding(self, text: str) -> List[float]:
        if not self.openai_client:
            return [0.0] * 1536
        response = await self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding

    async def index_milestone(
        self,
        summary_id: int,
        start_iter: int,
        end_iter: int,
        dense_summary: str
    ):
        embedding = await self.get_embedding(dense_summary)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.collection.upsert(
                ids=[str(summary_id)],
                embeddings=[embedding],
                documents=[dense_summary],
                metadatas=[{
                    "start_iteration": start_iter,
                    "end_iteration": end_iter,
                    "summary_id": summary_id
                }]
            )
        )
        logger.info(f"Indexed milestone #{summary_id} into ChromaDB vector store.")

    async def get_indexed_ids(self) -> Set[str]:
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.collection.get(include=[])["ids"]
            )
            return set(result)
        except Exception:
            return set()

    async def batch_index_milestones(self, milestones: List[Dict[str, Any]]):
        if not milestones or not self.openai_client:
            return

        texts = [m["dense_summary"] for m in milestones]
        response = await self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts
        )
        embeddings = [d.embedding for d in sorted(response.data, key=lambda x: x.index)]
        ids = [str(m["id"]) for m in milestones]
        documents = texts
        metadatas = [
            {
                "start_iteration": m["start_iteration"],
                "end_iteration": m["end_iteration"],
                "summary_id": m["id"]
            }
            for m in milestones
        ]

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
        )

    async def query_similar(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query_vector = await self.get_embedding(query)
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self.collection.query(
                query_embeddings=[query_vector],
                n_results=limit
            )
        )

        matches = []
        if results and results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            metadatas = results["metadatas"][0]
            documents = results["documents"][0]
            distances = results["distances"][0]

            for doc_id, meta, doc, dist in zip(ids, metadatas, documents, distances):
                matches.append({
                    "id": int(doc_id),
                    "start_iteration": meta["start_iteration"],
                    "end_iteration": meta["end_iteration"],
                    "dense_summary": doc,
                    "cosine_distance": dist
                })
        return matches
