"""Map one game to the native Proton in Steam's `config/config.vdf`.

The entry goes under InstallConfigStore/Software/Valve/Steam/CompatToolMapping,
the same shape Steam writes for a per-game choice in its own UI:

    "<appid>" { "name" "proton-cachyos-native"  "config" ""  "priority" "250" }

Steam itself records Valve's per-game defaults at priority 100. On 2026-11-22
Steam honoured a 250 entry: `compat_log.txt` named the native tool as the only
tool. A global default was never tested, so only per-game entries are written.

The file is edited as text, never round-tripped through a parser: every other
byte stays as Steam wrote it. It also holds private values (tokens, account
ids), so no line of it is ever logged or put in an error message -- errors
carry line numbers only. Steam rewrites the file from memory on exit, so a
write while it runs would be lost; it is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tempfile

from steam_installer import errors, recognize

TOOL = "proton-cachyos-native"
PRIORITY = "250"
VALVE_PRIORITY = "100"
_STEAM = ("installconfigstore", "software", "valve", "steam")
_MAPPING = (*_STEAM, "compattoolmapping")
# A quoted string (escapes allowed, newlines too), a brace, or anything else.
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}]|[^\s"{}]+')


class CompatMapError(errors.InstallerError):
    """Steam's config.vdf cannot be edited safely."""


@dataclass
class Outcome:
    """What editing the compat mapping did."""

    action: str  # "mapped", "already" or "kept"
    detail: str = ""


@dataclass
class _Entry:
    open_line: int  # the `{` after the appid key
    close_line: int = -1
    values: dict[str, str] = field(default_factory=dict)


@dataclass
class _Layout:
    lines: list[str]
    steam_open: int = -1
    mapping_open: int = -1
    entry: _Entry | None = None


def config_path(steam_root: Path) -> Path:
    """Path of Steam's ``config.vdf`` under *steam_root*."""
    return steam_root / "config" / "config.vdf"


def current(config: Path, appid: int) -> tuple[str, str] | None:
    """The (name, priority) the game is mapped to, or None when unmapped."""
    entry = _scan(_read(config), str(appid)).entry
    if entry is None:
        return None
    return entry.values.get("name", ""), entry.values.get("priority", "")


def keep_reason(entry: tuple[str, str] | None) -> Outcome | None:
    """Why :func:`map_app` would leave *entry* alone, or None when it would map.

    *entry* is :func:`current`'s ``(name, priority)``. The native tool is
    "already"; any other tool off Valve's priority is kuhy's own choice, "kept".
    """
    name, priority = entry or ("", "")
    if name == TOOL:
        return Outcome("already")
    if name and priority != VALVE_PRIORITY:
        return Outcome("kept", f"already mapped to {name} (priority {priority})")
    return None


def map_app(config: Path, appid: int) -> Outcome:
    """Point `appid` at the native Proton unless kuhy chose another tool."""
    pids = recognize.steam_client_pids()
    if pids:
        msg = (
            "Steam is running and would overwrite config.vdf on exit -- close it first"
        )
        raise CompatMapError(msg)
    layout = _scan(_read(config), str(appid))
    lines = layout.lines
    entry = layout.entry
    if entry is not None:
        name = entry.values.get("name", "")
        held = keep_reason((name, entry.values.get("priority", "")))
        if held is not None:
            return held
        key_line = entry.open_line - 1
        if (
            lines[key_line].strip() != f'"{appid}"'
            or lines[entry.close_line].strip() != "}"
        ):
            msg = f"config.vdf line {key_line + 1}: unexpected layout"
            raise CompatMapError(msg)
        indent = _indent(lines[entry.open_line])
        lines[key_line : entry.close_line + 1] = _entry(appid, indent)
        _write(config, lines)
        return Outcome("mapped", f"replaced Valve's choice {name or '(empty)'}")
    if layout.mapping_open >= 0:
        indent = _indent(lines[layout.mapping_open]) + "\t"
        lines[layout.mapping_open + 1 : layout.mapping_open + 1] = _entry(appid, indent)
    else:
        one = _indent(lines[layout.steam_open]) + "\t"
        block = [f'{one}"CompatToolMapping"\n', f"{one}{{\n"]
        block += [*_entry(appid, one + "\t"), f"{one}}}\n"]
        lines[layout.steam_open + 1 : layout.steam_open + 1] = block
    _write(config, lines)
    return Outcome("mapped")


def _read(config: Path) -> list[str]:
    try:
        return config.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        msg = f"cannot read {config}"
        raise CompatMapError(msg) from exc


def _tokens(lines: list[str]) -> list[tuple[str, int, bool]]:
    """(text, line index, is_quoted) for every token; quoted values may span lines."""
    text = "".join(lines)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    out: list[tuple[str, int, bool]] = []
    line_no = 0
    for match in _TOKEN.finditer(text):
        while starts[line_no + 1] <= match.start():
            line_no += 1
        piece = match.group(0)
        if piece[0] == '"':
            out.append((piece[1:-1], line_no, True))
        elif piece in "{}":
            out.append((piece, line_no, False))
        else:
            msg = f"config.vdf line {line_no + 1}: unexpected layout"
            raise CompatMapError(msg)
    return out


def _scan(lines: list[str], appid: str) -> _Layout:
    """Find the Steam block, its mapping block and the app's entry."""
    layout = _Layout(lines)
    stack: list[str] = []
    pending: str | None = None
    for text, index, quoted in _tokens(lines):
        entry = layout.entry if tuple(stack) == (*_MAPPING, appid) else None
        if quoted:
            if pending is None:
                pending = text
                continue
            if entry is not None:
                entry.values[pending.lower()] = text
            pending = None
        elif text == "{":
            if pending is None:
                msg = f"config.vdf line {index + 1}: block without a key"
                raise CompatMapError(msg)
            stack.append(pending.lower())
            pending = None
            _note_open(layout, tuple(stack), appid, index)
        else:
            if not stack or pending is not None:
                msg = f"config.vdf line {index + 1}: unbalanced brace"
                raise CompatMapError(msg)
            if entry is not None:
                entry.close_line = index
            stack.pop()
    if layout.steam_open < 0:
        msg = "config.vdf has no InstallConfigStore/Software/Valve/Steam"
        raise CompatMapError(msg)
    return layout


def _note_open(layout: _Layout, path: tuple[str, ...], appid: str, index: int) -> None:
    if (
        path in (_STEAM, _MAPPING, (*_MAPPING, appid))
        and layout.lines[index].strip() != "{"
    ):
        msg = f"config.vdf line {index + 1}: unexpected layout"
        raise CompatMapError(msg)
    if path == _STEAM:
        layout.steam_open = index
    elif path == _MAPPING:
        layout.mapping_open = index
    elif path == (*_MAPPING, appid):
        layout.entry = _Entry(open_line=index)


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _entry(appid: int, indent: str) -> list[str]:
    inner = indent + "\t"
    return [
        f'{indent}"{appid}"\n',
        f"{indent}{{\n",
        f'{inner}"name"\t\t"{TOOL}"\n',
        f'{inner}"config"\t\t""\n',
        f'{inner}"priority"\t\t"{PRIORITY}"\n',
        f"{indent}}}\n",
    ]


def _write(config: Path, lines: list[str]) -> None:
    """Replace the file atomically, keeping its permissions."""
    mode = config.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=config.parent, prefix=".config.vdf.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(lines))
        Path(tmp).chmod(mode)
        Path(tmp).replace(config)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
