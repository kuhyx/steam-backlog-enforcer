"""The research game: one game game-research may install and record.

kuhy 2026-11-21: to research a blocked game he adds it in game-research (the
PlayStudy wrapper). Not the total-block research *window*
(:mod:`_research_window`); this one is a standing slot, separate from the
manual picks and from the time-locked exceptions. The rules:

* **Two halves must agree.** game-research writes ``APPROVAL_FILE`` in kuhy's
  ``~/.config/game-research/`` and asks the daemon, over the control socket
  (``research_game`` op), to register it; the daemon keeps its own root
  record (``RECORD_FILE``) and logs every add and revoke to ``AUDIT_LOG``. A
  game is the research game only while both name the same app id, so a hand
  edit of the file never takes effect unaudited, and deleting the file (the
  game-research "remove") revokes it at once.
* **Kept the whole time it is on the list**: never uninstalled, its files
  never deleted, never hidden, never purged with Steam's data folder
  (:func:`kept_ids`).
* **Playable only while recorded**: the kill exemption holds only while a
  session flag game-research lists in the approval file names a live
  game-research wrapper (:func:`playable_ids`). Launched from plain Steam it
  is killed like any blocked game.
* **Fail closed**: a missing, malformed or disagreeing file is "no research
  game"; a flag that is unreadable, outside the home, stale or owned by any
  other process is "not recording".
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import time
from typing import Final

from steam_backlog_enforcer import config

logger = logging.getLogger(__name__)

HOME: Path = config.CONFIG_DIR.parent.parent
APPROVAL_FILE: Path = config.CONFIG_DIR.parent / "game-research" / "research_game.json"
RECORD_FILE: Path = Path("/var/lib/steam-backlog-enforcer/research_game.json")
AUDIT_LOG: Path = config.CONFIG_DIR / "exception_audit.log"
PROC: Path = Path("/proc")

# The launch flag spans "Steam asked to start the game" to "recording": the
# wrapper gives up on a window after 900 s (WINDOW_TIMEOUT_S), so an older
# flag is a leak, never a launch.
LAUNCH_FLAG_MAX_AGE_S: Final = 1200
_LAUNCH_FLAG_NAME: Final = "research_launch.pid"
_WRAPPER_NAMES: Final = ("game_research_desktop",)
_MAX_FLAGS: Final = 4


class ResearchGameError(ValueError):
    """The approval file does not allow the requested change."""


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def _app_id_of(data: object) -> int | None:
    if not isinstance(data, dict):
        return None
    app_id = data.get("app_id")
    if isinstance(app_id, bool) or not isinstance(app_id, int) or app_id <= 0:
        return None
    return app_id


def approved_app_id() -> int | None:
    """The app id game-research's approval file names, or ``None``."""
    return _app_id_of(_read_json(APPROVAL_FILE))


def research_game_id() -> int | None:
    """The research game: file and root record agree, else ``None``."""
    approved = approved_app_id()
    if approved is None or _app_id_of(_read_json(RECORD_FILE)) != approved:
        return None
    return approved


def kept_ids() -> frozenset[int]:
    """App ids that must stay installed, visible and on disk."""
    app_id = research_game_id()
    return frozenset() if app_id is None else frozenset({app_id})


def _is_wrapper(pid: int) -> bool:
    try:
        raw = (PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    return any(
        Path(arg).name.startswith(_WRAPPER_NAMES)
        for arg in raw.decode(errors="replace").split("\0")[:3]
    )


def _flag_live(raw: object) -> bool:
    if not isinstance(raw, str):
        return False
    flag = Path(raw)
    if not flag.is_absolute() or not flag.resolve().is_relative_to(HOME.resolve()):
        return False
    try:
        stat = flag.stat()
        pid = int(flag.read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return False
    if flag.name == _LAUNCH_FLAG_NAME and time.time() - stat.st_mtime > (
        LAUNCH_FLAG_MAX_AGE_S
    ):
        return False
    return pid > 0 and _is_wrapper(pid)


def session_live() -> bool:
    """Whether game-research is launching or recording right now."""
    data = _read_json(APPROVAL_FILE)
    flags = data.get("flags") if isinstance(data, dict) else None
    if not isinstance(flags, list):
        return False
    return any(_flag_live(f) for f in flags[:_MAX_FLAGS])


def playable_ids() -> frozenset[int]:
    """App ids spared from the unauthorized-game kill: kept and recorded."""
    kept = kept_ids()
    return kept if kept and session_live() else frozenset()


def _audit(app_id: int, event: str) -> None:
    stamp = datetime.now(UTC).isoformat()
    with contextlib.suppress(OSError):
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {event} app_id={app_id}\n")


def _write_record(payload: dict[str, object] | None) -> None:
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    if payload is None:
        RECORD_FILE.unlink(missing_ok=True)
        return
    tmp = RECORD_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(RECORD_FILE)


def register(app_id: int) -> dict[str, object]:
    """Register *app_id* as the research game; instant, no delay.

    Raises:
        ResearchGameError: the approval file does not name *app_id*.
    """
    approved = approved_app_id()
    if approved != app_id:
        msg = f"approval file names {approved}, not {app_id}"
        raise ResearchGameError(msg)
    record: dict[str, object] = {"app_id": app_id, "registered_at": time.time()}
    _write_record(record)
    _audit(app_id, "RESEARCH_GAME_ADDED")
    logger.warning("Research game registered: AppID=%d", app_id)
    return record


def revoke() -> int | None:
    """Drop the root record; return the app id it held (``None``: none)."""
    app_id = _app_id_of(_read_json(RECORD_FILE))
    if app_id is None:
        return None
    _write_record(None)
    _audit(app_id, "RESEARCH_GAME_REVOKED")
    logger.warning("Research game revoked: AppID=%d", app_id)
    return app_id
