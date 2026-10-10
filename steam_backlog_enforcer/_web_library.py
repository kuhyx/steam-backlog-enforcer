"""``GET /api/library``: every owned game, for the web library browser.

Joins the owned-games records (names, playtime, last played: see
:mod:`._owned_apps_cache`), the achievement snapshot, the HLTB cache, the
installed manifests and the state. Eligibility for "pick my own game" comes
from :func:`steam_backlog_enforcer._own_pick.ineligible_reason`, the same
rule the job enforces on the answer.

Reads local files only, except once: when no refresh has stored owned-game
records yet, it asks Steam for them (the snapshot alone misses every game
without achievements).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer import config as _config
from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._hltb_types import _read_raw_cache
from steam_backlog_enforcer._own_pick import ineligible_reason
from steam_backlog_enforcer._owned_apps_cache import (
    load_owned_records,
    owned_cache_stamp,
    refresh_owned_records,
)
from steam_backlog_enforcer._snapshot import load_snapshot
from steam_backlog_enforcer._web_io import ok
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.game_install import get_installed_games
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from steam_backlog_enforcer._web_io import Reply, Request


@dataclass(frozen=True)
class _SnapshotMemo:
    """The snapshot as achievement-free ``GameInfo``s, keyed by file stamp."""

    stamp: tuple[int, int]
    games: dict[int, GameInfo]


@dataclass
class _Memos:
    """The process-wide memos, each keyed by the stamp of its source file."""

    snapshot: _SnapshotMemo | None = None
    owned_ids: tuple[tuple[int, int], set[int]] | None = None


_MEMOS = _Memos()


def _snapshot_games() -> dict[int, GameInfo]:
    """Snapshot rows by app id; re-parsed only when the file changes.

    The snapshot is ~11 MB of per-achievement detail the library never
    shows, so one parse per file version, not one per request.
    """
    try:
        st = _config.SNAPSHOT_FILE.stat()
    except OSError:
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    memo = _MEMOS.snapshot
    if memo is None or memo.stamp != stamp:
        games = {
            int(row["app_id"]): GameInfo(
                app_id=int(row["app_id"]),
                name=str(row.get("name") or ""),
                total_achievements=int(row.get("total_achievements") or 0),
                unlocked_achievements=int(row.get("unlocked_achievements") or 0),
                playtime_minutes=int(row.get("playtime_minutes") or 0),
                completionist_hours=float(row.get("completionist_hours") or -1),
            )
            for row in load_snapshot() or []
            if "app_id" in row
        }
        memo = _MEMOS.snapshot = _SnapshotMemo(stamp, games)
    return memo.games


def _owned_records(config: Config) -> dict[int, dict[str, Any]]:
    """Owned-game records by app id; fetched once when none are cached."""
    records = load_owned_records(config.steam_id)
    if records is None:
        records = refresh_owned_records(config) or []
    return {int(r["app_id"]): r for r in records if "app_id" in r}


def _hltb_hours(
    app_id: int, game: GameInfo | None, hltb: dict[int, Any]
) -> float | None:
    """Completionist hours: the HLTB cache, else the snapshot, else unknown."""
    hours = float(hltb.get(app_id, {}).get("hours") or -1)
    if hours <= 0 and game is not None:
        hours = game.completionist_hours
    return round(hours, 1) if hours > 0 else None


def owned_app_ids() -> set[int]:
    """Every app id the library can list (the art route serves only these).

    Never asks Steam: an image request must not turn into an API call. Kept
    per owned-cache file version, since a grid load asks once per cover.
    """
    stamp = owned_cache_stamp()
    snapshot = _snapshot_games()
    memo = _MEMOS.owned_ids
    if memo is None or memo[0] != stamp:
        records = load_owned_records(Config.load().steam_id) or []
        ids = {int(r["app_id"]) for r in records if "app_id" in r}
        memo = _MEMOS.owned_ids = (stamp, ids)
    return set(snapshot) | memo[1]


def _reason(
    app_id: int,
    game: GameInfo | None,
    record: dict[str, Any],
    state: State,
    skipped: set[int],
) -> str | None:
    """:func:`ineligible_reason`, saying *why* a game has no scan data."""
    if game is None and record.get("has_stats") is False:
        return "No achievements"
    if game is None and record.get("has_stats"):
        return "Not scanned yet"
    return ineligible_reason(app_id, game, state, skipped)


def library_rows(state: State, config: Config) -> list[dict[str, object]]:
    """One contract ``LibraryGame`` per owned game, in no particular order."""
    snapshot = _snapshot_games()
    records = _owned_records(config)
    hltb = _read_raw_cache()
    installed = {app_id for app_id, _ in get_installed_games()}
    allowed = allowed_app_ids(state)
    skipped = state.active_skipped_ids()
    rows: list[dict[str, object]] = []
    for app_id in records.keys() | snapshot.keys():
        game = snapshot.get(app_id)
        record = records.get(app_id, {})
        rows.append(
            {
                "app_id": app_id,
                "name": record.get("name") or (game.name if game else str(app_id)),
                "achievements_total": game.total_achievements if game else 0,
                "achievements_unlocked": game.unlocked_achievements if game else 0,
                "hltb_hours": _hltb_hours(app_id, game, hltb),
                "playtime_minutes": int(
                    record.get("playtime_minutes")
                    or (game.playtime_minutes if game else 0)
                ),
                "last_played": int(record.get("last_played") or 0) or None,
                "installed": app_id in installed,
                "assigned": app_id in allowed,
                "ineligible_reason": _reason(app_id, game, record, state, skipped),
            }
        )
    return rows


def library_view(_request: Request) -> Reply:
    """``GET /api/library`` — every owned game as ``LibraryPayload``."""
    return ok({"games": library_rows(State.load(), Config.load())})
