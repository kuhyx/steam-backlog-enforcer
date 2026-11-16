"""The icon-word ledger file: the words (and glyph swaps) the user picked.

``{"version": 1, "icons": {"<icon id>": {"word": "<text>" | null,
"glyph": "<emoji>" | null}}}``. An absent id is unanswered; an entry without
a ``word`` key has a glyph choice but no word decision yet; ``word: null``
is a skip (no label); ``glyph: null`` keeps the registry's default.

It lives in the repo (``web/src/ui/icon_words.json``, committed by the user)
and is read by the web server at runtime, never by the build: a pick shows
on the next page load. ``SBE_ICON_WORDS`` points a scratch server at a copy.

Writes go to a sibling temp file and are renamed over the ledger, so a crash
mid-write leaves the previous file whole. A file that does not parse or does
not match the schema is copied aside as ``.corrupt`` (never over an older
copy) and every read fails loudly until someone fixes it: dropping it and
starting empty would silently lose the user's picks.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Final

LEDGER_ENV: Final = "SBE_ICON_WORDS"
LEDGER_NAME: Final = "icon_words.json"
DEFAULT_LEDGER: Final = (
    Path(__file__).resolve().parent.parent / "web" / "src" / "ui" / LEDGER_NAME
)
VERSION: Final = 1
# A repo file: world-readable like its neighbours (mkstemp would make it 0600).
FILE_MODE: Final = 0o644
_ENTRY_KEYS: Final = frozenset({"word", "glyph"})

type Ledger = dict[str, Any]


class LedgerCorruptError(Exception):
    """The ledger does not parse; *kept* holds the copy set aside."""

    def __init__(self, path: Path, kept: Path, why: str) -> None:
        """Name the broken file, its kept copy and what is wrong with it."""
        super().__init__(
            f"The icon-word ledger {path} is unreadable ({why}); a copy was kept "
            f"as {kept}. Fix or restore it (git checkout) to use icon words."
        )
        self.path = path
        self.kept = kept


def ledger_path() -> Path:
    """The ledger this process reads: ``$SBE_ICON_WORDS`` or the repo file."""
    override = os.environ.get(LEDGER_ENV)
    return Path(override) if override else DEFAULT_LEDGER


def is_ledger_file(path: Path) -> bool:
    """True for a ledger, its temp files and its corrupt copies (runtime data)."""
    name = path.name.lstrip(".")
    return name == LEDGER_NAME or name.startswith(f"{LEDGER_NAME}.")


def empty_ledger() -> Ledger:
    """A ledger with nothing answered."""
    return {"version": VERSION, "icons": {}}


def _schema_problem(data: object) -> str | None:
    """Why *data* is not a ledger, or None when it is one."""
    if not isinstance(data, dict) or set(data) != {"version", "icons"}:
        return "not a {version, icons} object"
    if data["version"] != VERSION:
        return f"version {data['version']!r} is not {VERSION}"
    if not isinstance(data["icons"], dict):
        return "icons is not an object"
    for icon, entry in data["icons"].items():
        if not isinstance(entry, dict) or not set(entry) <= _ENTRY_KEYS:
            return f"entry {icon!r} is not a {{word, glyph}} object"
        for key, value in entry.items():
            if value is not None and not isinstance(value, str):
                return f"{icon}.{key} is neither text nor null"
    return None


def _keep_aside(path: Path, raw: bytes) -> Path:
    """Copy *raw* next to *path* as ``.corrupt``; never overwrite an older copy."""
    kept = path.with_name(f"{path.name}.corrupt")
    if kept.exists():
        if kept.read_bytes() == raw:
            return kept
        kept = path.with_name(f"{path.name}.corrupt.{time.time_ns()}")
    kept.write_bytes(raw)
    return kept


def load_ledger(path: Path) -> Ledger:
    """Read the ledger at *path*; a missing file is an empty ledger.

    Raises:
        LedgerCorruptError: the file does not parse or match the schema
            (it is kept aside first, and left in place).
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return empty_ledger()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise LedgerCorruptError(path, _keep_aside(path, raw), str(exc)) from None
    why = _schema_problem(data)
    if why is not None:
        raise LedgerCorruptError(path, _keep_aside(path, raw), why)
    return data


def save_ledger(path: Path, ledger: Ledger) -> None:
    """Write *ledger* atomically: sibling temp file, fsync, rename over *path*.

    Sorted keys and a trailing newline keep the user's commits diffable.
    """
    text = json.dumps(ledger, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        Path(tmp).chmod(FILE_MODE)
        Path(tmp).replace(path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            Path(tmp).unlink()
        raise
