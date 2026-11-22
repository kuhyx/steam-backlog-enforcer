"""A read-only parser for Valve's KeyValues text (``config.vdf``, ``*.acf``).

Stdlib only: the root daemon runs on the system interpreter, which carries no
``vdf`` package, and an import that failed there would quietly turn every
decision built on it into "keep". Malformed input raises ``ValueError`` rather
than returning part of a tree, so a caller deciding something destructive can
fail closed. Error messages carry an offset, never file content: config.vdf
holds private values.
"""

from __future__ import annotations

import re
from typing import Final

type VdfNode = dict[str, VdfNode] | str

# One token per match: whitespace, a // comment, a quoted string (group 1), a
# brace (group 2), a [$PLATFORM] conditional, or a bare word (group 3).
_TOKEN: Final = re.compile(
    r'\s+|//[^\n]*|"((?:[^"\\]|\\.)*)"|([{}])|\[[^\]\n]*\]|([^\s"{}\[]+)',
    re.DOTALL,
)
_ESCAPES: Final = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
_ESCAPE: Final = re.compile(r"\\(.)", re.DOTALL)


def _malformed(offset: int) -> ValueError:
    return ValueError(f"malformed KeyValues at offset {offset}")


def _unescape(raw: str) -> str:
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(0)), raw)


def parse_vdf(text: str) -> dict[str, VdfNode]:
    """Parse KeyValues *text* into nested dicts (a repeated key: last wins).

    Raises:
        ValueError: on any unterminated string, stray or missing brace, or a
            key with no value.
    """
    root: dict[str, VdfNode] = {}
    stack = [root]
    key: str | None = None
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            raise _malformed(pos)
        quoted, brace, bare = match.groups()
        if brace == "{":
            if key is None:
                raise _malformed(pos)
            child: dict[str, VdfNode] = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if key is not None or len(stack) == 1:
                raise _malformed(pos)
            stack.pop()
        elif quoted is not None or bare is not None:
            word = _unescape(quoted) if quoted is not None else str(bare)
            if key is None:
                key = word
            else:
                stack[-1][key] = word
                key = None
        pos = match.end()
    if key is not None or len(stack) != 1:
        raise _malformed(pos)
    return root


def lookup(node: VdfNode | None, *keys: str) -> VdfNode | None:
    """Walk *keys* down from *node*, matching each one case-insensitively.

    Returns:
        The node found, or None when a key is missing or the path runs
        through a plain string.
    """
    for key in keys:
        if not isinstance(node, dict):
            return None
        wanted = key.casefold()
        node = next((v for k, v in node.items() if k.casefold() == wanted), None)
    return node
