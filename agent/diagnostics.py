from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional

class FailureOrigin(str, Enum):
    LLM_MALFORMED = "LLM_MALFORMED"                   # Non-parsable Python emitted
    AST_SECURITY_REJECTED = "AST_SECURITY_REJECTED"   # Rejected by zero-trust allowlist
    WASM_TRAP = "WASM_TRAP"                           # Fuel depletion, crash, or div-by-zero in WASM
    Z3_REFUTED = "Z3_REFUTED"                         # Counterexample found by SMT solver (CEGIS)
    LEAN_KERNEL = "LEAN_KERNEL"                       # Lean 4 typechecker/kernel compilation error
    BENCHMARK_LOW = "BENCHMARK_LOW"                   # Valid code, but sub-baseline packing ratio

@dataclass
class PipelineDiagnostic:
    success: bool
    origin: Optional[FailureOrigin] = None
    detail: str = ""
    candidate_code: str = ""
    execution_time_ms: float = 0.0
    fitness: float = 0.0
    canonical_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.origin:
            d["origin"] = self.origin.value
        return d
