import logging
from typing import Any, Dict
from agent.cognitive_memory import CognitiveMemoryStore
from agent.hybrid_search import HybridEpisodicRetriever

logger = logging.getLogger("MemoryTools")

def build_memory_tools(memory_store: CognitiveMemoryStore):
    async def update_core_memory_handler(arguments: Dict[str, Any]) -> str:
        key = arguments.get("key", "").strip()
        value = arguments.get("value", "").strip()
        if not key or not value:
            return "Error: Both key and value must be non-empty."
        await memory_store.update_core_memory(key, value)
        return f"Successfully updated core memory: [{key}] = {value}"

    return update_core_memory_handler

def build_search_tools(retriever: HybridEpisodicRetriever):
    async def search_memory_handler(arguments: Dict[str, Any]) -> str:
        query = arguments.get("query", "").strip()
        top_k = int(arguments.get("top_k", 3))
        if not query:
            return "Error: query parameter cannot be empty."

        results = await retriever.search(query=query, top_k=top_k)
        if not results:
            return f"No historical episodic summaries found matching: '{query}'."

        formatted = [f"=== Search Results for '{query}' ==="]
        for idx, r in enumerate(results, start=1):
            formatted.append(
                f"{idx}. [Cycles #{r['start_iteration']}-#{r['end_iteration']}] "
                f"(Score: {r['rrf_score']}, Sources: {', '.join(r['matched_sources'])})\n"
                f"{r['dense_summary']}"
            )
        return "\n\n".join(formatted)

    return search_memory_handler
