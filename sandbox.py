import asyncio
import logging
from typing import List, Tuple
from agent.wasm_sandbox import wasm_engine
from agent.gvisor_sandbox import gvisor_engine
from agent.wat_compiler import compile_python_to_wat

logger = logging.getLogger("Sandbox")

def evaluate_heuristic_dual(
    code_str: str,
    sequences: List[List[float]],
    timeout_sec: float = 5.0
) -> Tuple[bool, float, str]:
    """
    Tier 1: Sub-millisecond WebAssembly JIT with fuel metering
    Tier 2: Hardened container isolation (gVisor runsc) fallback
    """
    try:
        wat_code = compile_python_to_wat(code_str)
        ok_compile, module, _ = wasm_engine.compile_wat(wat_code)
        if ok_compile and module:
            ok, score, err = wasm_engine.score_benchmark_wasm(module, sequences)
            if ok:
                return True, score, ""
    except Exception:
        pass

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        return gvisor_engine._local_fallback(code_str, sequences)
    else:
        return loop.run_until_complete(
            gvisor_engine.score_benchmark_sandboxed(code_str, sequences, timeout_sec)
        )
