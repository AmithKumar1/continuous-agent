from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class PortScanArgs(BaseModel):
    host: str = Field(..., description="Target hostname or IP address to inspect.")
    ports: Optional[List[int]] = Field(
        default=[80, 443, 8080, 8443, 3000, 5000],
        description="TCP port list to scan."
    )

class SecurityHeadersArgs(BaseModel):
    url: str = Field(..., description="Target HTTP/HTTPS URL to check for security headers.")

class ZapScanArgs(BaseModel):
    target_url: str = Field(..., description="Target application URL for OWASP ZAP spider and passive scanning.")

class UpdateCoreMemoryArgs(BaseModel):
    key: str = Field(..., description="Unique memory slot identifier.")
    value: str = Field(..., description="Factual string to store in working memory.")

class SearchMemoryArgs(BaseModel):
    query: str = Field(..., description="Natural language search phrase to query historical episodic memories.")
    top_k: Optional[int] = Field(default=3, description="Number of results to retrieve.")

class VerifyLean4Args(BaseModel):
    lean_code: str = Field(..., description="Lean 4 proof script or theorem declaration.")

class VerifyZ3Args(BaseModel):
    python_code: str = Field(..., description="Python heuristic implementation to check against mathematical invariants.")

class AlphaCodeArgs(BaseModel):
    problem_spec: str = Field(..., description="Problem description to synthesize candidate solutions for.")

class CreateGitHubPRArgs(BaseModel):
    python_code: str = Field(..., description="Verified Python code.")
    lean_proof: str = Field(..., description="Accompanying formal Lean 4 proof.")
    fitness_score: float = Field(..., description="Empirical benchmark score.")
    algorithm_name: Optional[str] = Field(default="DiscoveredHeuristic", description="Descriptive algorithm name.")

# Dashboard API schemas
class CoreMemoryPayload(BaseModel):
    key: str
    value: str

class HeuristicPayload(BaseModel):
    category: str
    condition: str
    actionable_lesson: str

class ScheduleUpdateRequest(BaseModel):
    cron_expression: str = Field(..., description="Standard 5-part cron pattern, e.g., '0 2 * * *'")

class VerificationRequest(BaseModel):
    python_code: Optional[str] = None
    code: Optional[str] = None
    timeout_ms: Optional[int] = 1500

    def get_code(self) -> str:
        return self.python_code or self.code or ""

class SynthesisRequest(BaseModel):
    python_code: str

class PRCreationRequest(BaseModel):
    python_code: str
    lean_proof: str
    fitness_score: float
    algorithm_name: Optional[str] = "OnlineBinPackingHeuristic"

class FunSearchStartRequest(BaseModel):
    evals_per_island: Optional[int] = 20
