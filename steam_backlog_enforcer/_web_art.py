"""``GET /api/art/{app_id}``: a game's portrait cover for the library grid.

Looked for in order: Steam's own librarycache (portrait files only; the
40-hex ``.jpg`` there are 32x32 icons and ``header.jpg`` is landscape), this
server's disk cache of earlier CDN fetches, then Steam's CDN. No cover is a
404 and the UI draws a title tile instead.

The one view that may use the network, so it is fenced: owned app ids only
(the id is an int put into a fixed URL, never a proxy), a few fetches at a
time with a short timeout, and a failed fetch is remembered for a while so a
grid of 1000+ tiles does not re-ask a blocked or missing CDN on every
scroll. A 404 is remembered for a week; a network failure (the total block
lists ``steamstatic.com``) for minutes, so art appears once it lifts.
"""

from __future__ import annotations

import contextlib
from http import HTTPStatus
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING, Final

import requests

from steam_backlog_enforcer._web_errors import not_found
from steam_backlog_enforcer._web_io import Reply
from steam_backlog_enforcer._web_library import owned_app_ids

if TYPE_CHECKING:
    from steam_backlog_enforcer._web_io import Request

LIBRARYCACHE = Path("~/.local/share/Steam/appcache/librarycache").expanduser()
ART_CACHE_DIR = Path.home() / ".cache" / "steam_backlog_enforcer" / "art"

_CDN: Final = (
    "https://shared.steamstatic.com/store_item_assets/steam/apps/"
    "{app_id}/library_600x900.jpg"
)
_PORTRAITS: Final = ("library_600x900.jpg", "library_capsule.jpg")
_NOT_FOUND_RETRY_S: Final = 7 * 24 * 3600
_FAILED_RETRY_S: Final = 10 * 60
_TIMEOUT: Final = (3.05, 6.0)
_MAX_BYTES: Final = 2 * 1024 * 1024
_HEADERS: Final = {"Cache-Control": "private, max-age=86400"}
_fetch_slots = threading.BoundedSemaphore(6)


def _local_cover(app_id: int) -> Path | None:
    """A portrait Steam itself cached for *app_id*, if any."""
    base = LIBRARYCACHE / str(app_id)
    for name in _PORTRAITS:
        for candidate in (base / name, *sorted(base.glob(f"*/{name}"))):
            if candidate.is_file():
                return candidate
    return None


def _cache_file(app_id: int) -> Path:
    return ART_CACHE_DIR / f"{app_id}.jpg"


def _miss_file(app_id: int) -> Path:
    return ART_CACHE_DIR / f"{app_id}.miss"


def _miss_active(app_id: int) -> bool:
    """Whether a recent fetch failed and it is too early to retry."""
    try:
        retry_at = float(_miss_file(app_id).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return time.time() < retry_at


def _record_miss(app_id: int, seconds: int) -> None:
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _miss_file(app_id).write_text(str(time.time() + seconds), encoding="utf-8")


def _store(app_id: int, body: bytes) -> None:
    """Write the cover atomically so a reader never sees half a JPEG."""
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ART_CACHE_DIR / f"{app_id}.jpg.{threading.get_ident()}.tmp"
    tmp.write_bytes(body)
    tmp.replace(_cache_file(app_id))
    with contextlib.suppress(OSError):
        _miss_file(app_id).unlink()


def _fetch(app_id: int) -> bytes | None:
    """Download the CDN cover into the cache; ``None`` when there is none."""
    with _fetch_slots:
        # Another request may have fetched it while this one waited.
        with contextlib.suppress(OSError):
            return _cache_file(app_id).read_bytes()
        if _miss_active(app_id):
            return None
        try:
            resp = requests.get(_CDN.format(app_id=app_id), timeout=_TIMEOUT)
        except requests.RequestException:
            _record_miss(app_id, _FAILED_RETRY_S)
            return None
        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code != HTTPStatus.OK or not ctype.startswith("image/"):
            missing = resp.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN}
            _record_miss(app_id, _NOT_FOUND_RETRY_S if missing else _FAILED_RETRY_S)
            return None
        if len(resp.content) > _MAX_BYTES:
            _record_miss(app_id, _NOT_FOUND_RETRY_S)
            return None
        _store(app_id, resp.content)
        return resp.content


def cover_bytes(app_id: int) -> bytes | None:
    """The cover for *app_id* from the first source that has one."""
    local = _local_cover(app_id)
    if local is not None:
        return local.read_bytes()
    with contextlib.suppress(OSError):
        return _cache_file(app_id).read_bytes()
    if _miss_active(app_id):
        return None
    return _fetch(app_id)


def art_view(request: Request) -> Reply:
    """``GET /api/art/{app_id}`` — JPEG bytes, or ``not_found``."""
    raw = request.args[0]
    if not raw.isdigit() or int(raw) not in owned_app_ids():
        msg = f"{raw} is not an owned game."
        raise not_found(msg)
    body = cover_bytes(int(raw))
    if body is None:
        msg = f"No cover art for {raw}."
        raise not_found(msg)
    return Reply(HTTPStatus.OK, raw=body, ctype="image/jpeg", headers=_HEADERS)
