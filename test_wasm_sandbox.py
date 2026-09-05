import time
from agent.wat_compiler import compile_python_to_wat
from agent.wasm_sandbox import wasm_engine

def run_tests():
    print("Testing WebAssembly Sandbox & WAT Compiler...")

    valid_code = """
def priority(item: float, bin_capacity: float) -> float:
    return item / bin_capacity
""".strip()

    wat = compile_python_to_wat(valid_code)
    print("Compiled WAT snippet:\n", "\n".join(wat.splitlines()[:10]), "\n...")

    ok_compile, module, err = wasm_engine.compile_wat(wat)
    assert ok_compile, f"Compilation failed: {err}"
    print("✓ WAT module compiled into machine JIT bytecode successfully.")

    sequences = [[10.0, 20.0, 30.0], [50.0, 25.0]]
    start = time.time()
    ok_exec, score, err_exec = wasm_engine.score_benchmark_wasm(module, sequences)
    elapsed_us = (time.time() - start) * 1_000_000
    assert ok_exec, f"Execution failed: {err_exec}"
    print(f"✓ WASM In-Process Execution Score: {score:.4f} (Elapsed: {elapsed_us:.1f} μs)")

    print("All WASM tests passed successfully!")

if __name__ == "__main__":
    run_tests()
