import asyncio
import hashlib
import re
from typing import Any, Dict, List
from agent.frontier_router import frontier_router

class AlphaCode2Ensemble:
    def __init__(self, sample_size: int = 6):
        self.sample_size = sample_size

    def _extract_code(self, raw_text: str) -> str:
        blocks = re.findall(r"```python\s*(.*?)\s*```", raw_text, re.DOTALL)
        if blocks:
            return blocks[0].strip()
        return raw_text.strip()

    async def generate_and_cluster(self, problem_spec: str) -> Dict[str, Any]:
        tasks = [
            frontier_router.generate(
                prompt=f"Synthesize an optimal heuristic function priority(item, bin_capacity) for:\n{problem_spec}\nOutput pure python.",
                temperature=0.8
            )
            for _ in range(self.sample_size)
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        valid_candidates = []
        clusters: Dict[str, List[str]] = {}

        for resp in responses:
            if isinstance(resp, str) and "def priority" in resp:
                code = self._extract_code(resp)
                valid_candidates.append(code)
                sig = hashlib.sha256(code.encode("utf-8")).hexdigest()[:8]
                clusters.setdefault(sig, []).append(code)

        # Rank clusters by consensus density
        ranked_clusters = sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)
        top_candidates = [candidates[0] for _, candidates in ranked_clusters[:3]]

        return {
            "total_sampled": len(valid_candidates),
            "clusters_count": len(clusters),
            "top_candidates": top_candidates
        }

alphacode_pipeline = AlphaCode2Ensemble()
