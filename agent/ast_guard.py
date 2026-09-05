import ast
from typing import Set, Type

class SecurityError(Exception):
    """Raised when candidate code violates the zero-trust AST allowlist."""
    pass

ALLOWED_NODES: Set[Type[ast.AST]] = {
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.IfExp,
    ast.Compare,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
    ast.Expr,
    ast.Pass,
    ast.Load,
    ast.Store
}

SAFE_CALL_FUNCTIONS: Set[str] = {"max", "min", "abs", "round"}

def sanitize_ast(code_str: str) -> None:
    """
    Enforces mathematical purity on candidate priority heuristic code.
    Rejects imports, file I/O, loops, system calls, lambdas, and attribute access.
    """
    try:
        tree = ast.parse(code_str.strip())
    except SyntaxError as se:
        raise SecurityError(f"Malformed syntax in candidate heuristic: {se}")

    for node in ast.walk(tree):
        node_type = type(node)
        if node_type not in ALLOWED_NODES:
            raise SecurityError(f"Unsafe AST element rejected: {node_type.__name__}")

        # Prevent accessing double-underscore internal attributes or dunders
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise SecurityError(f"Internal attribute access rejected: {node.id}")
            # Explicit ban on built-in dangerous callables even as identifiers
            if node.id in {"eval", "exec", "open", "compile", "globals", "locals", "__import__"}:
                raise SecurityError(f"Forbidden identifier referenced: {node.id}")

        if isinstance(node, ast.Attribute):
            raise SecurityError(f"Attribute access forbidden: {node.attr}")

        # Strictly restrict function calls to pure mathematical built-ins (max, min, abs, round)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise SecurityError("Complex function invocation targets forbidden.")
            if node.func.id not in SAFE_CALL_FUNCTIONS:
                raise SecurityError(f"Unauthorized function call forbidden: {node.func.id}")
