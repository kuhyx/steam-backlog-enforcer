"""Textgate guard: desktop toasts paint glyphs and numbers, never words.

Walks every ``send_notification`` / ``notify_desktop_user`` call in the
package and checks the literal parts of its arguments (string constants and
the constant pieces of f-strings). Interpolated values -- game names, app ids,
durations, shell commands -- are content and pass. A module-level constant
passed by name is resolved too, so ``_TITLE`` cannot hide a sentence.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

_PKG = Path(__file__).resolve().parents[1]
_TOAST_CALLS = {"send_notification", "notify_desktop_user"}
_WORD = re.compile(r"[A-Za-z]{2,}")


def _literal_parts(node: ast.expr, consts: dict[str, ast.expr]) -> list[str]:
    """The literal text an argument paints, following module constants.

    Args:
        node: One call argument.
        consts: Module-level ``NAME = <expr>`` assignments.

    Returns:
        Every literal string fragment in the argument.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
    if isinstance(node, ast.Name) and node.id in consts:
        return _literal_parts(consts[node.id], consts)
    if isinstance(node, ast.Subscript):
        return _literal_parts(node.value, consts)
    if isinstance(node, ast.Dict):
        return [p for v in node.values for p in _literal_parts(v, consts)]
    return []


def _module_consts(tree: ast.Module) -> dict[str, ast.expr]:
    """Map module-level simple assignments to their value expressions.

    Args:
        tree: A parsed module.

    Returns:
        ``{name: value}`` for ``NAME = value`` and ``NAME: T = value``.
    """
    out: dict[str, ast.expr] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = stmt.value
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
        ):
            out[stmt.target.id] = stmt.value
    return out


def _toast_words() -> list[str]:
    """Every literal word passed to a toast, as ``file:line: text``.

    Returns:
        The offending fragments; empty when every toast is word-free.
    """
    hits: list[str] = []
    for path in sorted(_PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_consts(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in _TOAST_CALLS:
                continue
            for arg in node.args:
                hits.extend(
                    f"{path.name}:{node.lineno}: {part}"
                    for part in _literal_parts(arg, consts)
                    if _WORD.search(part)
                )
    return hits


def test_toasts_paint_no_words() -> None:
    """No toast title or body carries a literal 2+ letter word."""
    assert _toast_words() == []


def test_the_guard_finds_toast_calls() -> None:
    """The walk is not vacuous: the package has toast call sites."""
    calls = 0
    for path in _PKG.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            func = getattr(node, "func", None)
            name = getattr(func, "id", None) or getattr(func, "attr", "")
            calls += isinstance(node, ast.Call) and name in _TOAST_CALLS
    assert calls >= 8
