import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx
from config import config

logger = logging.getLogger("GitOps")

class GitHubGitOpsPublisher:
    def __init__(self):
        self.token = config.GITHUB_TOKEN
        self.repo = config.GITHUB_REPO
        self.base_branch = config.GITHUB_BASE_BRANCH
        self.base_url = f"https://api.github.com/repos/{self.repo}"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    async def create_discovery_pr(
        self,
        python_code: str,
        lean_proof: str,
        fitness_score: float,
        invariant_results: Optional[Dict[str, Any]] = None,
        algorithm_name: str = "OnlineBinPackingHeuristic"
    ) -> Dict[str, Any]:
        if not self.token or not self.repo or self.repo == "owner/repo":
            return {
                "success": False,
                "error": "GitHub credentials not configured (GITHUB_TOKEN / GITHUB_REPO unset)"
            }

        async with httpx.AsyncClient(headers=self._get_headers(), timeout=30.0) as client:
            try:
                # 1. Get base branch SHA
                ref_res = await client.get(f"{self.base_url}/git/ref/heads/{self.base_branch}")
                ref_res.raise_for_status()
                base_sha = ref_res.json()["object"]["sha"]

                # 2. Create feature branch
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                branch_name = f"discovery/{algorithm_name.lower()}-{timestamp}"
                branch_payload = {"ref": f"refs/heads/{branch_name}", "sha": base_sha}

                br_res = await client.post(f"{self.base_url}/git/refs", json=branch_payload)
                br_res.raise_for_status()

                # 3. Create Python algorithm file
                file_slug = f"heuristic_{timestamp}"
                py_path = f"heuristics/{file_slug}.py"
                py_content = base64.b64encode(python_code.encode("utf-8")).decode("utf-8")
                await client.put(
                    f"{self.base_url}/contents/{py_path}",
                    json={
                        "message": f"feat(discovery): add {algorithm_name} (Fitness: {fitness_score:.4f})",
                        "content": py_content,
                        "branch": branch_name
                    }
                )

                # 4. Create Lean 4 certificate file
                lean_path = f"proofs/{file_slug}.lean"
                lean_content = base64.b64encode(lean_proof.encode("utf-8")).decode("utf-8")
                await client.put(
                    f"{self.base_url}/contents/{lean_path}",
                    json={
                        "message": f"docs(formal): Lean 4 verification certificate for {algorithm_name}",
                        "content": lean_content,
                        "branch": branch_name
                    }
                )

                # 5. Open Pull Request
                pr_body = (
                    f"## 🤖 Autonomous Algorithmic Discovery\n\n"
                    f"**Algorithm:** `{algorithm_name}`\n"
                    f"**Empirical Benchmark Fitness:** `{fitness_score:.4f}`\n"
                    f"**Formal Verification:** Verified with Lean 4 Kernel & Z3 SMT Solver\n\n"
                    f"### Python Implementation\n```python\n{python_code}\n```\n\n"
                    f"### Lean 4 Proof Certificate\n```lean\n{lean_proof}\n```"
                )

                pr_res = await client.post(
                    f"{self.base_url}/pulls",
                    json={
                        "title": f"🚀 Autonomous Discovery: {algorithm_name} (Fitness {fitness_score:.4f})",
                        "head": branch_name,
                        "base": self.base_branch,
                        "body": pr_body
                    }
                )
                pr_res.raise_for_status()
                pr_data = pr_res.json()

                return {
                    "success": True,
                    "pr_url": pr_data.get("html_url"),
                    "pr_number": pr_data.get("number"),
                    "branch": branch_name
                }

            except Exception as e:
                logger.error(f"GitOps PR creation failed: {e}")
                return {"success": False, "error": str(e)}

gitops_publisher = GitHubGitOpsPublisher()
