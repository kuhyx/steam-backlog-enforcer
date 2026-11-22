"""``GET /api/compat``: every installed game's compat-tool (Proton) decision.

The rows come from the merged installer's own decision code
(``steam_installer.compat_rows``, the same rows ``--map-installed`` logs), so
the view can never disagree with what the apply job does. Deciding parses
Steam's ~10 MB app cache and reads the anti-cheat list, so the answer is kept
in memory and rebuilt only when one of the files it was decided from changes
(apply rewrites config.vdf, an install adds a manifest). The anti-cheat list
is reused from its on-disk cache for :data:`ANTICHEAT_MAX_AGE`: a GET never
waits on the network unless that cache is older.

The apply job (``map-installed``) checks its ids here too: :func:`checked_appids`.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Final, cast

from steam_backlog_enforcer._command_params import InvalidParamsError
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_io import Reply, ok
from steam_installer import anticheat, appinfo_cache, compat_decide, compat_map
from steam_installer.compat_apply import TOOL_DIR, Context
from steam_installer.compat_rows import rows
from steam_installer.errors import InstallerError
from steam_installer.library import find_steam_root, list_libraries

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from steam_backlog_enforcer._web_io import Request

ANTICHEAT_MAX_AGE: Final = 6 * 3600.0

_lock = threading.Lock()
_memo: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}


def clear_cache() -> None:
    """Forget the memoised payload (tests)."""
    with _lock:
        _memo.clear()


def _stat(path: Path) -> tuple[str, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return str(path), st.st_mtime_ns, st.st_size


def cache_key(root: Path) -> tuple[object, ...]:
    """Stats of every file a decision reads, plus the anti-cheat age window."""
    paths = [
        appinfo_cache.default_path(),
        compat_map.config_path(root),
        root / "steamapps" / "libraryfolders.vdf",
        anticheat.CACHE,
        compat_decide.OVERRIDES,
        root / TOOL_DIR / "VERSION",
    ]
    for library in list_libraries(root):
        paths += sorted(library.steamapps.glob("appmanifest_*.acf"))
    return (int(time.time() // ANTICHEAT_MAX_AGE), *(_stat(p) for p in paths))


def compat_payload() -> dict[str, object]:
    """``{tool, tool_ready, rows}``, from memory while no input file changed.

    Raises:
        InstallerError: Steam's app cache or config.vdf cannot be read.
        OSError: No Steam installation.
        ValueError: The overrides file is malformed.
    """
    root = find_steam_root()
    key = cache_key(root)
    with _lock:
        hit = _memo.get("payload")
        if hit is not None and hit[0] == key:
            return hit[1]
        context = Context(root, anticheat_max_age=ANTICHEAT_MAX_AGE)
        payload: dict[str, object] = {
            "tool": compat_map.TOOL,
            "tool_ready": context.tool_ready,
            "rows": [row.to_json() for row in rows(root, context=context)],
        }
        _memo["payload"] = (key, payload)
        return payload


def compat_view(_request: Request) -> Reply:
    """``GET /api/compat``.

    Raises:
        ApiError: ``op_failed`` when the decision inputs cannot be read.
    """
    try:
        return ok(compat_payload())
    except (InstallerError, OSError, ValueError) as exc:
        raise ApiError(str(exc), code="op_failed") from None


def _rows() -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", compat_payload()["rows"])


def checked_appids(raw: str | None) -> list[int]:
    """The ids an apply maps: *raw* checked, or every game that would change.

    Raises:
        InvalidParamsError: *raw* is not comma-separated digits, names a game
            that is not installed, or there is nothing to map.
    """
    table = _rows()
    if raw is None:
        ids = [int(str(r["app_id"])) for r in table if r["changes"]]
    else:
        parts = [part.strip() for part in raw.split(",")]
        if not all(part.isdigit() for part in parts):
            msg = f"appids must be comma-separated app ids, got {raw!r}"
            raise InvalidParamsError(msg)
        ids = list(dict.fromkeys(int(part) for part in parts))
        known = {r["app_id"] for r in table}
        missing = [str(i) for i in ids if i not in known]
        if missing:
            msg = f"Not installed: {', '.join(missing)}"
            raise InvalidParamsError(msg)
    if not ids:
        msg = "Nothing to map: no installed game would change."
        raise InvalidParamsError(msg)
    return ids


def phrase_fields(params: Mapping[str, object]) -> dict[str, object]:
    """The ``map-installed`` phrase's slots: how many games the job is given."""
    raw = params.get("appids")
    return {"appid_count": len(checked_appids(None if raw is None else str(raw)))}
