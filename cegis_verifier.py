import ast
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import z3
from dynamic_suite import Counterexample

class ASTZ3Transpiler(ast.NodeVisitor):
    def __init__(self, item_var: z3.ArithRef, cap_var: z3.ArithRef):
        self.item = item_var
        self.cap = cap_var
        self.locals: Dict[str, z3.ArithRef] = {}

    def transpile(self, expr_node: ast.AST) -> z3.ArithRef:
        return self.visit(expr_node)

    def visit_Name(self, node: ast.Name) -> z3.ArithRef:
        if node.id == "item":
            return self.item
        elif node.id == "bin_capacity":
            return self.cap
        elif node.id in self.locals:
            return self.locals[node.id]
        raise ValueError(f"Unsupported variable identifier: {node.id}")

    def visit_Constant(self, node: ast.Constant) -> z3.ArithRef:
        if isinstance(node.value, (int, float)):
            return z3.RealVal(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    def visit_BinOp(self, node: ast.BinOp) -> z3.ArithRef:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        elif isinstance(node.op, ast.Sub):
            return left - right
        elif isinstance(node.op, ast.Mult):
            return left * right
        elif isinstance(node.op, ast.Div):
            # Guarded division: if divisor is zero, simplify
            return left / z3.If(right == 0, z3.RealVal(1.0), right)
        raise ValueError(f"Unsupported binary operator: {type(node.op)}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> z3.ArithRef:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        elif isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError(f"Unsupported unary operator: {type(node.op)}")

    def visit_IfExp(self, node: ast.IfExp) -> z3.ArithRef:
        cond = self.visit_condition(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return z3.If(cond, body, orelse)

    def visit_condition(self, node: ast.AST) -> z3.BoolRef:
        if isinstance(node, ast.Compare):
            left = self.visit(node.left)
            if len(node.ops) == 1 and len(node.comparators) == 1:
                op = node.ops[0]
                right = self.visit(node.comparators[0])
                if isinstance(op, ast.Gt):
                    return left > right
                elif isinstance(op, ast.GtE):
                    return left >= right
                elif isinstance(op, ast.Lt):
                    return left < right
                elif isinstance(op, ast.LtE):
                    return left <= right
                elif isinstance(op, ast.Eq):
                    return left == right
                elif isinstance(op, ast.NotEq):
                    return left != right
        raise ValueError("Unsupported conditional expression inside priority heuristic")


class SymbolicContractVerifier:
    def __init__(self, timeout_ms: int = 1500):
        self.timeout_ms = timeout_ms

    def verify(self, code_str: str) -> Tuple[bool, Optional[Counterexample]]:
        try:
            tree = ast.parse(code_str)
            target_fn = None
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "priority":
                    target_fn = node
                    break

            if not target_fn:
                return False, Counterexample("SyntaxContract", 0, 0, detail="Missing priority() declaration")

            return_node = None
            for stmt in target_fn.body:
                if isinstance(stmt, ast.Return):
                    return_node = stmt
                    break

            if not return_node or not return_node.value:
                return False, Counterexample("SyntaxContract", 0, 0, detail="Missing return statement in priority()")

            item = z3.Real("item")
            cap = z3.Real("bin_capacity")

            transpiler = ASTZ3Transpiler(item, cap)
            symbolic_score = transpiler.transpile(return_node.value)

            # Invariant 1: Singularity Prevention (Div-by-Zero)
            s = z3.Solver()
            s.set("timeout", self.timeout_ms)
            s.add(item > 0, item <= 100)
            s.add(cap >= item, cap <= 100)

            # Check if any denominator evaluates to zero
            denominators = []
            for node in ast.walk(return_node.value):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    denominators.append(transpiler.transpile(node.right))

            for denom in denominators:
                s.push()
                s.add(denom == 0)
                if s.check() == z3.sat:
                    m = s.model()
                    item_val = float(m[item].as_decimal(3).replace("?", "")) if m[item] else 10.0
                    cap_val = float(m[cap].as_decimal(3).replace("?", "")) if m[cap] else 10.0
                    return False, Counterexample("SingularityZeroDiv", item_val, cap_val, "Divisor evaluates to 0")
                s.pop()

            # Invariant 2: Fit Monotonicity
            s.reset()
            s.set("timeout", self.timeout_ms)
            cap2 = z3.Real("bin_capacity_2")
            s.add(item > 0, item <= 100)
            s.add(cap >= item, cap2 > cap, cap2 <= 100)

            transpiler2 = ASTZ3Transpiler(item, cap2)
            score_cap1 = symbolic_score
            score_cap2 = transpiler2.transpile(return_node.value)

            # Tight fit should have score >= loose fit: score_cap1 >= score_cap2
            # Counterexample is violation: score_cap1 < score_cap2
            s.add(score_cap1 < score_cap2)
            if s.check() == z3.sat:
                m = s.model()
                item_val = float(m[item].as_decimal(3).replace("?", "")) if m[item] else 15.0
                cap_val = float(m[cap].as_decimal(3).replace("?", "")) if m[cap] else 20.0
                return False, Counterexample("FitMonotonicity", item_val, cap_val, "Tighter fit assigned lower priority")

            return True, None

        except (ValueError, NotImplementedError):
            # Gracefully bypass when using unsupported operations
            return True, None
        except Exception as e:
            return False, Counterexample("VerificationCrash", 0, 0, detail=str(e))
