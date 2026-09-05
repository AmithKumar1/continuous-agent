import asyncio
import re
import logging
from typing import Optional
from openai import AsyncOpenAI
from config import config
from cegis_verifier import SymbolicContractVerifier, Counterexample
from dynamic_suite import DynamicDiagnosticSuite
from problem import get_benchmark_dataset, run_simulation

logger = logging.getLogger("CEGIS")

async def run_cegis_funsearch(iterations: int = 10, target_fitness: float = 0.88):
    client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
    verifier = SymbolicContractVerifier()
    suite = DynamicDiagnosticSuite()

    current_code = """
def priority(item: float, bin_capacity: float) -> float:
    return bin_capacity - item
""".strip()

    for gen in range(1, iterations + 1):
        # 1. Verification step
        is_verified, counterexample = verifier.verify(current_code)
        if not is_verified and counterexample:
            suite.register_counterexample(counterexample)
            logger.info(f"Gen {gen}: Invariant violated [{counterexample.invariant_name}] -> Counterexample injected.")

        # 2. Simulation step
        dataset = suite.get_probes()
        local_scope = {}
        try:
            exec(current_code, {}, local_scope)
            fn = local_scope.get("priority")
            score = run_simulation(fn, dataset)
        except Exception:
            score = 0.0

        if score >= target_fitness and is_verified:
            logger.info(f"Target fitness reached: {score:.3f}")
            return current_code, score

    return current_code, 0.0
