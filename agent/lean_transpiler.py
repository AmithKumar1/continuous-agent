import ast
from fractions import Fraction
from typing import Dict, List, Set

class PythonToLean4Transpiler(ast.NodeVisitor):
    def __init__(self):
        self.denominators: List[str] = []

    def visit_Name(self, node: ast.Name) -> str:
        if node.id in ("item", "bin_capacity"):
            return node.id
        return node.id

    def visit_Constant(self, node: ast.Constant) -> str:
        if isinstance(node.value, (int, float)):
            f = Fraction(str(node.value)).limit_denominator(1000)
            if f.denominator == 1:
                return f"({f.numerator} : \u211a)"
            return f"(({f.numerator} : \u211a) / ({f.denominator} : \u211a))"
        raise ValueError(f"Unsupported constant type in AST: {type(node.value)}")

    def visit_BinOp(self, node: ast.BinOp) -> str:
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return f"({left} + {right})"
        elif isinstance(node.op, ast.Sub):
            return f"({left} - {right})"
        elif isinstance(node.op, ast.Mult):
            return f"({left} * {right})"
        elif isinstance(node.op, ast.Div):
            self.denominators.append(right)
            return f"({left} / {right})"
        raise ValueError(f"Unsupported operator: {type(node.op)}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> str:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return f"(-{operand})"
        elif isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError(f"Unsupported unary operator: {type(node.op)}")

def transpile_priority_ast(python_code: str) -> Dict[str, Any]:
    tree = ast.parse(python_code)
    target_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "priority":
            target_fn = node
            break

    if not target_fn:
        raise ValueError("No priority function defined in AST")

    ret_stmt = None
    for stmt in target_fn.body:
        if isinstance(stmt, ast.Return):
            ret_stmt = stmt
            break

    if not ret_stmt or not ret_stmt.value:
        raise ValueError("Missing return expression in priority function")

    transpiler = PythonToLean4Transpiler()
    lean_expr = transpiler.visit(ret_stmt.value)

    return {
        "lean_expr": lean_expr,
        "denominators": transpiler.denominators
    }
