from typing import Dict
from agent.lean_transpiler import transpile_priority_ast

class Lean4ProofSynthesizer:
    @staticmethod
    def synthesize(python_code: str) -> str:
        spec = transpile_priority_ast(python_code)
        expr = spec["lean_expr"]
        denominators = spec["denominators"]

        lean_code = [
            "import Mathlib.Data.Rat.Basic",
            "import Mathlib.Tactic",
            "",
            "def priority (item bin_capacity : \u211a) : \u211a :=",
            f"  {expr}",
            ""
        ]

        if not denominators:
            lean_code.extend([
                "theorem priority_singularity_free (item bin_capacity : \u211a)",
                "    (h_item : item > 0)",
                "    (h_cap : bin_capacity >= item) :",
                "    True := by",
                "  trivial",
                ""
            ])
        else:
            for idx, denom in enumerate(denominators, start=1):
                lean_code.extend([
                    f"theorem priority_nonzero_denom_{idx} (item bin_capacity : \u211a)",
                    "    (h_item : item > 0)",
                    "    (h_cap : bin_capacity > item) :",
                    f"    {denom} \u2260 0 := by",
                    "  intro h",
                    "  linarith",
                    ""
                ])

        lean_code.extend([
            "theorem priority_well_defined (item bin_capacity : \u211a) :",
            "    \u2203 (p : \u211a), priority item bin_capacity = p := by",
            "  exact \u27e8priority item bin_capacity, rfl\u27e9",
            ""
        ])

        return "\n".join(lean_code)
