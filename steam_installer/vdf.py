"""Minimal reader/writer for Valve's KeyValues (VDF) text format.

Steam uses this format for appmanifest_*.acf and libraryfolders.vdf.
(Its binary cousin, appcache/appinfo.vdf, is read by :mod:`appinfo_cache`.)
Only the plain-text variant is supported (no binary VDF) -- that covers every
file this project touches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from steam_installer import errors

# A string, or a nested block of the same shape. Left as Any (the original
# alias was a bare string, which mypy reads as Any): callers narrow with
# isinstance and tests index into parsed manifests freely.
type VdfValue = Any


@dataclass
class VdfParseError(errors.InstallerError):
    """Text is not valid VDF."""

    message: str
    position: int

    def __str__(self) -> str:
        """The parse error with its position."""
        return f"{self.message} (at position {self.position})"


def parse(text: str) -> dict[str, VdfValue]:
    """Parse VDF text into a nested dict. Returns the top-level block's contents."""
    tokens = _tokenize(text)
    pos = 0

    def parse_block() -> tuple[dict[str, VdfValue], int]:
        nonlocal pos
        result: dict[str, VdfValue] = {}
        while pos < len(tokens):
            piece = tokens[pos]
            if piece == "}":
                pos += 1
                return result, pos
            key = piece
            pos += 1
            if pos >= len(tokens):
                msg = f"unexpected end of input after key {key!r}"
                raise VdfParseError(msg, pos)
            if tokens[pos] == "{":
                pos += 1
                block, pos = parse_block()
                result[key] = block
            else:
                result[key] = tokens[pos]
                pos += 1
        return result, pos

    # A VDF file is one root key followed by one root block.
    if not tokens:
        return {}
    root_key = tokens[0]
    pos = 1
    if pos >= len(tokens) or tokens[pos] != "{":
        msg = "expected '{' after root key"
        raise VdfParseError(msg, pos)
    pos += 1
    root_value, pos = parse_block()
    return {root_key: root_value}


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch in "{}":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            tokens.append("".join(buf))
            i = j + 1
            continue
        # Unquoted token (rare in Steam's own files, but tolerate it).
        j = i
        while j < n and text[j] not in " \t\r\n{}":
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def _escape(value: str) -> str:
    r"""Re-escape a value for VDF output.

    The tokenizer consumes `\` escapes, so a manifest holding
    `_CommonRedist\\vcredist\\2015\\installscript.vdf` parses to a value with
    single backslashes. Writing that back verbatim would halve them on every
    parse/dump cycle and silently corrupt the path -- confirmed against the
    real appmanifest_228980.acf (Steamworks Common Redistributables), whose
    InstallScripts entries are Windows paths and whose depot 228989 is shared
    with other games.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def dumps(root_key: str, data: dict[str, VdfValue], indent: str = "\t") -> str:
    """Serialize a dict back to VDF text, matching Steam's own tab-indented style."""
    lines = [f'"{root_key}"', "{"]
    _dump_block(data, indent, 1, lines)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _dump_block(
    data: dict[str, VdfValue], indent: str, depth: int, lines: list[str]
) -> None:
    prefix = indent * depth
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f'{prefix}"{_escape(key)}"')
            lines.append(f"{prefix}{{")
            _dump_block(value, indent, depth + 1, lines)
            lines.append(f"{prefix}}}")
        else:
            lines.append(f'{prefix}"{_escape(key)}"\t\t"{_escape(value)}"')
