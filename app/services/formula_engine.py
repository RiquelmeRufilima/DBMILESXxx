from __future__ import annotations

import ast
import math
from typing import Any


class FormulaError(ValueError):
    pass


_ALLOWED_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_ALLOWED_UNARY = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}

_ALLOWED_FUNCTIONS = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
}


def _to_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise FormulaError(f"Valor não numérico: {value!r}") from exc


def evaluate_formula(formula: str, variables: dict[str, Any]) -> float:
    if not formula or not formula.strip():
        raise FormulaError("A fórmula está vazia.")

    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Fórmula inválida: {exc.msg}") from exc

    # Converte só variáveis simples/númericas. Metadados de tela (_scope, _meta etc.)
    # são salvos junto da cotação, mas não fazem parte da fórmula.
    numeric_variables = {}
    for key, value in variables.items():
        if str(key).startswith("_") or isinstance(value, (dict, list, tuple, set)):
            continue
        numeric_variables[key] = _to_number(value)

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in numeric_variables:
                raise FormulaError(f"Variável desconhecida: {node.id}")
            return numeric_variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY:
            left = evaluate(node.left)
            right = evaluate(node.right)
            try:
                return float(_ALLOWED_BINARY[type(node.op)](left, right))
            except ZeroDivisionError as exc:
                raise FormulaError("Divisão por zero na fórmula.") from exc
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return float(_ALLOWED_UNARY[type(node.op)](evaluate(node.operand)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = _ALLOWED_FUNCTIONS.get(node.func.id)
            if function is None:
                raise FormulaError(f"Função não permitida: {node.func.id}")
            if node.keywords:
                raise FormulaError("Argumentos nomeados não são permitidos.")
            args = [evaluate(arg) for arg in node.args]
            return float(function(*args))
        raise FormulaError(f"Operação não permitida: {type(node).__name__}")

    result = evaluate(tree)
    if not math.isfinite(result):
        raise FormulaError("A fórmula gerou um valor inválido.")
    return round(float(result), 2)


def validate_formula(formula: str, allowed_variables: set[str]) -> tuple[bool, str]:
    fake_values = {name: 1 for name in allowed_variables}
    try:
        evaluate_formula(formula, fake_values)
        return True, "Fórmula válida"
    except FormulaError as exc:
        return False, str(exc)
