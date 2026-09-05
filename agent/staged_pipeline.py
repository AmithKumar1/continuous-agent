import time
import logging
from typing import List, Optional, Tuple
from agent.ast_cache import ast_cache, compute_ast_hash
from agent.ast_guard import sanitize_ast, SecurityError
from agent.diagnostics import FailureOrigin, PipelineDiagnostic
from agent.wat_compiler import compile_python_to_wat
from agent.wasm_sandbox import wasm_engine
from agent.cegis_verifier import SymbolicContractVerifier
from agent.cegis_tracker import tracker
from sandbox import evaluate_heuristic_dual

logger = logging.getLogger("StagedPipeline")

class StagedEvaluationPipeline:
    """
    Staged Fail-Fast Pipeline:
      Stage 0: Semantic AST Memoization Cache (<0.1ms)
      Stage 1: AST Syntax & Zero-Trust Allowlist Check (<1ms)
      Stage 2: Micro-WASM Smoke Test (<50µs)
      Stage 3: Z3 Invariant Probe (<15ms) -> CEGIS Buffer on failure
      Stage 4: Full Dual-Sandbox Benchmark Suite (<2ms)
      Stage 5: Lean 4 Formal Synthesis (for champion discoveries)
    """

    def __init__(self, baseline_fitness_threshold: float = 0.82):
        self.baseline_threshold = baseline_fitness_threshold
        self.verifier = SymbolicContractVerifier(timeout_ms=1500)

    def evaluate(
        self,
        code_str: str,
        sequences: List[List[float]],
        island_id: int = 0
    ) -> PipelineDiagnostic:
        t0 = time.perf_counter()
        canonical_hash = compute_ast_hash(code_str)

        # Stage 0: Cache Check
        cached = ast_cache.get(code_str)
        if cached is not None:
            fitness, diag_dict = cached
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return PipelineDiagnostic(
                success=fitness > 0.0,
                origin=FailureOrigin(diag_dict["origin"]) if diag_dict.get("origin") else None,
                detail="Cache hit (memoized evaluation)",
                candidate_code=code_str,
                execution_time_ms=elapsed_ms,
                fitness=fitness,
                canonical_hash=canonical_hash
            )

        # Stage 1: AST Syntax & Zero-Trust Allowlist Check (<1ms)
        try:
            sanitize_ast(code_str)
        except SecurityError as se:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            diag = PipelineDiagnostic(
                success=False,
                origin=FailureOrigin.AST_SECURITY_REJECTED,
                detail=str(se),
                candidate_code=code_str,
                execution_time_ms=elapsed_ms,
                fitness=0.0,
                canonical_hash=canonical_hash
            )
            ast_cache.put(code_str, 0.0, diag.to_dict())
            return diag
        except SyntaxError as syn:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            diag = PipelineDiagnostic(
                success=False,
                origin=FailureOrigin.LLM_MALFORMED,
                detail=f"Syntax Error: {syn}",
                candidate_code=code_str,
                execution_time_ms=elapsed_ms,
                fitness=0.0,
                canonical_hash=canonical_hash
            )
            ast_cache.put(code_str, 0.0, diag.to_dict())
            return diag

        # Stage 2: Micro-WASM Smoke Test (<50µs)
        try:
            wat_code = compile_python_to_wat(code_str)
            ok_compile, module, compile_err = wasm_engine.compile_wat(wat_code)
            if ok_compile and module:
                smoke_seq = [[20.0, 50.0], [10.0, 30.0]]
                ok_smoke, _, smoke_err = wasm_engine.score_benchmark_wasm(module, smoke_seq)
                if not ok_smoke:
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    diag = PipelineDiagnostic(
                        success=False,
                        origin=FailureOrigin.WASM_TRAP,
                        detail=f"WASM Smoke Trap: {smoke_err}",
                        candidate_code=code_str,
                        execution_time_ms=elapsed_ms,
                        fitness=0.0,
                        canonical_hash=canonical_hash
                    )
                    ast_cache.put(code_str, 0.0, diag.to_dict())
                    return diag
        except Exception as e:
            logger.debug(f"WASM smoke test bypassed or errored: {e}")

        # Stage 3: Z3 Invariant Probe (<15ms)
        try:
            ok_z3, ce = self.verifier.verify(code_str)
            if not ok_z3 and ce:
                tracker.record_counterexample(ce, source=f"island_{island_id}")
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                cap_val = getattr(ce, "bin_capacity", getattr(ce, "cap", 0.0))
                diag = PipelineDiagnostic(
                    success=False,
                    origin=FailureOrigin.Z3_REFUTED,
                    detail=f"SMT Refuted: {ce.invariant_name} (item={ce.item:.2f}, cap={cap_val:.2f})",
                    candidate_code=code_str,
                    execution_time_ms=elapsed_ms,
                    fitness=0.0,
                    canonical_hash=canonical_hash
                )
                ast_cache.put(code_str, 0.0, diag.to_dict())
                return diag
        except Exception as z3_err:
            logger.debug(f"Z3 verification error: {z3_err}")

        # Stage 4: Full Benchmark Suite (<2ms)
        ok_eval, fitness, eval_err = evaluate_heuristic_dual(code_str, sequences)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if not ok_eval:
            diag = PipelineDiagnostic(
                success=False,
                origin=FailureOrigin.BENCHMARK_LOW,
                detail=f"Benchmark execution failed: {eval_err}",
                candidate_code=code_str,
                execution_time_ms=elapsed_ms,
                fitness=0.0,
                canonical_hash=canonical_hash
            )
            ast_cache.put(code_str, 0.0, diag.to_dict())
            return diag

        origin = FailureOrigin.BENCHMARK_LOW if fitness < self.baseline_threshold else None
        diag = PipelineDiagnostic(
            success=True,
            origin=origin,
            detail="Benchmark evaluation passed",
            candidate_code=code_str,
            execution_time_ms=elapsed_ms,
            fitness=fitness,
            canonical_hash=canonical_hash
        )
        ast_cache.put(code_str, fitness, diag.to_dict())
        return diag

staged_pipeline = StagedEvaluationPipeline()
