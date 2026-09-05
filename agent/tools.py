import asyncio
import httpx
from typing import Any, Callable, Dict, List, Optional
from agent.schemas import (
    PortScanArgs, SecurityHeadersArgs, ZapScanArgs,
    UpdateCoreMemoryArgs, SearchMemoryArgs, VerifyLean4Args,
    VerifyZ3Args, AlphaCodeArgs, CreateGitHubPRArgs
)
from agent.security_tools import scan_ports, check_http_security_headers
from agent.security_zap import run_zap_scan_tool
from agent.formal_verifier import lean_verifier
from cegis_verifier import SymbolicContractVerifier
from agent.alphacode_ensemble import alphacode_pipeline
from agent.gitops import gitops_publisher

class ToolRegistry:
    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self.schemas: List[Dict[str, Any]] = []

    def register(self, name: str, schema_cls: Any, handler: Callable):
        self._handlers[name] = handler
        self.schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": schema_cls.__doc__ or name,
                "parameters": schema_cls.model_json_schema()
            }
        })

    def get_handler(self, name: str) -> Optional[Callable]:
        return self._handlers.get(name)

registry = ToolRegistry()

# 1. Web Fetch
async def fetch_web_page(args: Dict[str, Any]) -> str:
    url = args.get("url", "")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)
        return resp.text[:1500]

# 2. Formal Verification Tools
async def verify_lean4_handler(args: Dict[str, Any]) -> str:
    code = args.get("lean_code", "")
    ok, msg = await lean_verifier.verify_code(code)
    return f"Lean 4 Verification: {'PASS' if ok else 'FAIL'}\nDetails: {msg}"

async def verify_z3_handler(args: Dict[str, Any]) -> str:
    code = args.get("python_code", "")
    verifier = SymbolicContractVerifier()
    ok, ce = verifier.verify(code)
    if ok:
        return "Z3 SMT Invariant Verification: PASS (All contract boundaries satisfied)"
    return f"Z3 SMT Violation detected: [{ce.invariant_name}] -> Item={ce.item}, Cap={ce.bin_capacity}. Detail: {ce.detail}"

async def alphacode_handler(args: Dict[str, Any]) -> str:
    spec = args.get("problem_spec", "")
    res = await alphacode_pipeline.generate_and_cluster(spec)
    return str(res)

async def gitops_pr_handler(args: Dict[str, Any]) -> str:
    res = await gitops_publisher.create_discovery_pr(
        python_code=args.get("python_code", ""),
        lean_proof=args.get("lean_proof", ""),
        fitness_score=float(args.get("fitness_score", 0.0)),
        algorithm_name=args.get("algorithm_name", "AutonomousHeuristic")
    )
    return str(res)

# Register default core tools
registry.register("scan_ports", PortScanArgs, scan_ports)
registry.register("check_http_security_headers", SecurityHeadersArgs, check_http_security_headers)
registry.register("run_zap_security_scan", ZapScanArgs, run_zap_scan_tool)
registry.register("verify_lean4_proof", VerifyLean4Args, verify_lean4_handler)
registry.register("verify_z3_invariants", VerifyZ3Args, verify_z3_handler)
registry.register("alphacode_solve", AlphaCodeArgs, alphacode_handler)
registry.register("create_github_pr", CreateGitHubPRArgs, gitops_pr_handler)
