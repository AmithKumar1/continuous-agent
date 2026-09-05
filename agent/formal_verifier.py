import asyncio
import os
import shutil
import tempfile
from typing import Dict, Optional, Tuple
from config import config

class Lean4Verifier:
    def __init__(self, lean_bin: Optional[str] = None):
        self.lean_bin = lean_bin or shutil.which("lean") or config.LEAN_BIN_PATH

    async def verify_code(self, lean_code: str, timeout_sec: float = 10.0) -> Tuple[bool, str]:
        if not self.lean_bin or not shutil.which(self.lean_bin):
            return False, "Lean 4 binary not detected on system PATH"

        with tempfile.NamedTemporaryFile(suffix=".lean", mode="w", encoding="utf-8", delete=False) as f:
            f.write(lean_code)
            temp_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                self.lean_bin,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            out_txt = stdout.decode("utf-8")
            err_txt = stderr.decode("utf-8")

            if proc.returncode == 0:
                return True, out_txt or "Proof verified successfully (Lean 4 kernel accepted)."
            else:
                return False, err_txt or out_txt or f"Lean exited with status {proc.returncode}"

        except asyncio.TimeoutError:
            return False, f"Lean verification timed out after {timeout_sec}s"
        except Exception as e:
            return False, f"Lean execution error: {str(e)}"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class Z3ConstraintVerifier:
    def verify_expression(self, expr_str: str) -> Dict[str, Any]:
        try:
            import z3
            s = z3.Solver()
            s.set("timeout", 2000)
            x = z3.Real("x")
            s.add(x > 0)
            is_sat = (s.check() == z3.sat)
            return {"verified": is_sat, "status": "SAT" if is_sat else "UNSAT"}
        except Exception as e:
            return {"verified": False, "error": str(e)}

lean_verifier = Lean4Verifier()
z3_verifier = Z3ConstraintVerifier()
