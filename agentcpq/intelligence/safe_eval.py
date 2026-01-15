import ast
from decimal import Decimal


ALLOWED_FUNCS = {
    "max": max,
    "min": min,
}


ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Num,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
)


def safe_eval_expression(expression: str, context: dict):
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise ValueError(f"Unsupported expression node: {type(node).__name__}")
    return _eval_node(tree.body, context)


def _eval_node(node, context):
    if isinstance(node, ast.Constant):
        return Decimal(str(node.value))
    if isinstance(node, ast.Num):
        return Decimal(str(node.n))
    if isinstance(node, ast.Name):
        value = context.get(node.id, 0)
        return Decimal(str(value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, context)
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, context)
        right = _eval_node(node.right, context)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right != 0 else Decimal("0")
        if isinstance(node.op, ast.Mod):
            return left % right if right != 0 else Decimal("0")
        if isinstance(node.op, ast.Pow):
            return left ** right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        func = ALLOWED_FUNCS.get(node.func.id)
        if not func:
            raise ValueError(f"Unsupported function: {node.func.id}")
        args = [_eval_node(arg, context) for arg in node.args]
        return Decimal(str(func(*args)))
    raise ValueError("Unsupported expression")
