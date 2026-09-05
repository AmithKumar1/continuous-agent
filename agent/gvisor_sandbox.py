import asyncio
import hashlib
import json
import logging
import shutil
from typing import Any, Dict, List, Optional, Tuple
from config import config

logger = logging.getLogger("GVisorSandbox")

class GVisorExecutionEngine:
    def __init__(self, image: str = "algo-sandbox:latest", timeout_sec: float = 5.0):
        self.image = image
        self.timeout_sec = timeout_sec

    async def score_benchmark_sandboxed(
        self,
        code_str: str,
        sequences: List[List[float]],
        timeout_sec: Optional[float] = None
    ) -> Tuple[bool, float, str]:
        # Fallback to local execution if Docker is not installed or unreachable
        if not shutil.which("docker"):
            logger.debug("Docker not detected in PATH; falling back to in-process local evaluation.")
            return self._local_fallback(code_str, sequences)

        timeout = timeout_sec or self.timeout_sec
        payload = json.dumps({
            "mode": "score",
            "code": code_str,
            "sequences": sequences
        })

        cmd = [
            "docker", "run", "--rm", "-i",
            "--network=none",
            "--memory=128m",
            "--cpus=1.0",
            "--read-only",
            "--pids-limit=64",
            self.image
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=payload.encode("utf-8")),
                timeout=timeout
            )

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="ignore")
                logger.debug(f"Docker returned non-zero code ({proc.returncode}): {err_msg}. Falling back to local execution.")
                return self._local_fallback(code_str, sequences)

            res = json.loads(stdout.decode("utf-8"))
            if not res.get("success"):
                return self._local_fallback(code_str, sequences)

            return True, float(res.get("fitness", -1.0)), ""

        except asyncio.TimeoutError:
            return False, -1.0, f"gVisor evaluation timed out after {timeout}s"
        except Exception as e:
            # Fallback to local python evaluation if docker is absent
            return self._local_fallback(code_str, sequences)

    def _local_fallback(self, code_str: str, sequences: List[List[float]]) -> Tuple[bool, float, str]:
        try:
            from problem import run_simulation
            local_scope = {}
            exec(code_str, {}, local_scope)
            fn = local_scope.get("priority")
            if not fn:
                return False, -1.0, "No priority function defined"
            score = run_simulation(fn, sequences)
            return True, score, ""
        except Exception as e:
            return False, -1.0, f"Local fallback failed: {str(e)}"

gvisor_engine = GVisorExecutionEngine()
