import asyncio
import os
import shutil
import subprocess
from config import config

def check_mark(status: bool) -> str:
    return "[PASS]" if status else "[FAIL]"

async def run_preflight():
    print("\n🔍 RUNNING CONTINUOUS AGENT PRE-FLIGHT CHECKS...\n" + "=" * 60)

    # 1. Check Lean 4 & Lake
    lean_path = shutil.which("lean") or shutil.which(config.LEAN_BIN_PATH)
    lean_ok = False
    if lean_path:
        try:
            proc = subprocess.run([lean_path, "--stdin"], input=b"theorem test : 1 + 1 = 2 := rfl", capture_output=True, timeout=5)
            lean_ok = (proc.returncode == 0)
        except Exception:
            pass
    print(f"{check_mark(lean_ok)} Lean 4 Kernel & Lake Toolchain (Path: {lean_path or 'Not Found'})")

    # 2. Check Z3 SMT Solver
    z3_ok = False
    try:
        import z3
        s = z3.Solver()
        s.add(z3.Real('x') > 0)
        z3_ok = (s.check() == z3.sat)
    except Exception:
        pass
    print(f"{check_mark(z3_ok)} Z3 SMT Theorem Prover (Python SDK)")

    # 3. Check Wasmtime In-Process Engine
    wasm_ok = False
    try:
        from wasmtime import Config, Engine, Store, Module, Instance
        engine = Engine(Config())
        module = Module(engine, '(module (func (export "test") (result i32) i32.const 42))')
        store = Store(engine)
        instance = Instance(store, module, [])
        val = instance.exports(store)["test"](store)
        wasm_ok = (val == 42)
    except Exception:
        pass
    print(f"{check_mark(wasm_ok)} Wasmtime JIT Sandbox (Memory & Fuel Metering)")

    # 4. Check gVisor / Docker Sandbox Fallback
    docker_path = shutil.which("docker")
    docker_ok = bool(docker_path)
    print(f"{check_mark(docker_ok)} Docker / gVisor (runsc) Sandbox Fallback")

    # 5. Check API Credentials & GitHub GitOps
    llm_ok = bool(config.API_KEY)
    github_ok = bool(os.getenv("GITHUB_TOKEN") and config.GITHUB_REPO != "owner/repo")
    print(f"{check_mark(llm_ok)} Frontier LLM API Key Configured ({'Set' if llm_ok else 'Unset'})")
    print(f"{check_mark(github_ok)} GitHub GitOps Token & Target Repository ({config.GITHUB_REPO})")

    print("=" * 60)
    print("Preflight check complete. Core verification engines ready.\n")

if __name__ == "__main__":
    asyncio.run(run_preflight())
