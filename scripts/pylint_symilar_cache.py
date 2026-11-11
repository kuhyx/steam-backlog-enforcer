"""Pylint plugin: hash each file once for the duplicate-code check (R0801).

pylint's similarity checker compares every pair of linted files, and
``Symilar._find_common`` calls ``symilar.hash_lineset`` on BOTH files of every
pair. With ~550 files that is ~150 000 hashings of the same ~550 files, and it
was the slowest part of a whole-tree pylint run (well over 28 s of ~55 s under
the resource cap).

``hash_lineset`` is a pure function of a file's stripped lines and the window
size, and ``_find_common`` only reads the two dicts it returns (the line limits
it mutates are ``copy.copy``-ed first). Caching the result per (file, window)
therefore yields the same R0801 messages, computed once per file.

Fails closed: if a pylint upgrade changes ``hash_lineset``'s signature, this
raises instead of caching a function whose contract it no longer knows.

Loaded through ``load-plugins`` in pyproject.toml; the ``init-hook`` there puts
the repo root on ``sys.path`` first, which makes ``scripts.`` importable.
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING

from pylint.checkers import symilar

if TYPE_CHECKING:
    from collections.abc import Callable

    from pylint.lint import PyLinter

    HashResult = tuple[symilar.HashToIndex_T, symilar.IndexToLines_T]
    HashFunc = Callable[[symilar.LineSet, int], HashResult]

EXPECTED_PARAMS = ("lineset", "min_common_lines")


def memoise(func: HashFunc) -> HashFunc:
    """Wrap ``hash_lineset`` with a per-(file, window) cache.

    The key is ``id(lineset)``; the cache keeps the lineset itself alive and
    checks identity on a hit, so a recycled id can never return another
    file's hashes.
    """
    cache: dict[tuple[int, int], tuple[symilar.LineSet, HashResult]] = {}

    @functools.wraps(func)
    def cached(
        lineset: symilar.LineSet,
        min_common_lines: int = symilar.DEFAULT_MIN_SIMILARITY_LINE,
    ) -> HashResult:
        key = (id(lineset), min_common_lines)
        hit = cache.get(key)
        if hit is None or hit[0] is not lineset:
            hit = (lineset, func(lineset, min_common_lines))
            cache[key] = hit
        return hit[1]

    return cached


def register(_linter: PyLinter) -> None:
    """Patch ``symilar.hash_lineset`` once per process (pylint plugin hook)."""
    current = symilar.hash_lineset
    if hasattr(current, "__wrapped__"):
        return
    params = tuple(inspect.signature(current).parameters)
    if params != EXPECTED_PARAMS:
        msg = (
            f"pylint_symilar_cache: symilar.hash_lineset{params} no longer "
            f"matches {EXPECTED_PARAMS}; re-check that it is still pure and "
            "update scripts/pylint_symilar_cache.py"
        )
        raise RuntimeError(msg)
    symilar.hash_lineset = memoise(current)
