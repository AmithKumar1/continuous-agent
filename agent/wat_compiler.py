import ast
from typing import Dict, List

class PythonToWatCompiler(ast.NodeVisitor):
    def __init__(self):
        self.instructions: List[str] = []

    def visit_Return(self, node: ast.Return):
        if node.value:
            self.visit(node.value)

    def visit_Name(self, node: ast.Name):
        if node.id == "item":
            self.instructions.append("local.get $item")
        elif node.id == "bin_capacity":
            self.instructions.append("local.get $cap")
        else:
            raise ValueError(f"Undefined variable in WASM emission: {node.id}")

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, (int, float)):
            val = float(node.value)
            self.instructions.append(f"f64.const {val}")
        else:
            raise ValueError("Unsupported literal type")

    def visit_BinOp(self, node: ast.BinOp):
        self.visit(node.left)
        self.visit(node.right)
        if isinstance(node.op, ast.Add):
            self.instructions.append("f64.add")
        elif isinstance(node.op, ast.Sub):
            self.instructions.append("f64.sub")
        elif isinstance(node.op, ast.Mult):
            self.instructions.append("f64.mul")
        elif isinstance(node.op, ast.Div):
            self.instructions.append("f64.div")
        else:
            raise ValueError("Unsupported binary operator for WAT")

    def visit_UnaryOp(self, node: ast.UnaryOp):
        self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            self.instructions.append("f64.neg")
        elif not isinstance(node.op, ast.UAdd):
            raise ValueError("Unsupported unary operator for WAT")

def compile_python_to_wat(code_str: str) -> str:
    tree = ast.parse(code_str)
    fn_def = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "priority":
            fn_def = node
            break

    if not fn_def:
        raise ValueError("Missing priority function")

    compiler = PythonToWatCompiler()
    for stmt in fn_def.body:
        compiler.visit(stmt)

    body_wat = "\n    ".join(compiler.instructions)

    wat_module = f"""(module
  (memory (export "memory") 1 1)
  (func $priority (export "priority") (param $item f64) (param $cap f64) (result f64)
    {body_wat}
  )
)"""
    return wat_module
