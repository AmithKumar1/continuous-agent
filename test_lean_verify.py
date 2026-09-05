import asyncio
import httpx
from agent.lean_synthesizer import Lean4ProofSynthesizer
from agent.formal_verifier import lean_verifier

async def run_test():
    python_heuristic = """
def priority(item: float, bin_capacity: float) -> float:
    # First-Fit descending ratio
    return item / (bin_capacity + 1.0)
""".strip()

    print("Transpiling and synthesizing Lean 4 proof skeleton...")
    synthesized_lean = Lean4ProofSynthesizer.synthesize(python_heuristic)
    print("Generated Lean 4 Code:\n" + "-" * 40)
    print(synthesized_lean)
    print("-" * 40)

    print("Running formal kernel verification...")
    ok, msg = await lean_verifier.verify_code(synthesized_lean)
    print(f"Lean 4 Kernel Result: {'VERIFIED' if ok else 'FAILED'}")
    print(f"Kernel Output: {msg}")

if __name__ == "__main__":
    asyncio.run(run_test())
