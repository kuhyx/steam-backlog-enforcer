"""Read-only API views: status, stats, installed games, commands, backups.

Each builder returns the contract payload (``web/src/api/contract.ts``) and
reads only local state and caches — never ``config.json`` secrets, never the
network. They are the same numbers the CLI prints, projected to JSON.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer import _steam_state
from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._backups import list_backups
from steam_backlog_enforcer._budget_view import build_budget_snapshot
from steam_backlog_enforcer._command_catalog import command_specs
from steam_backlog_enforcer._manual_pick_lifecycle import status_payload
from steam_backlog_enforcer._web_dataset import build_web_dataset, dataset_to_payload
from steam_backlog_enforcer._web_io import Reply, ok
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.game_install import get_installed_games, is_protected_app

if TYPE_CHECKING:
    from steam_backlog_enforcer._web_io import Request

_SIZE_ON_DISK = re.compile(r'"SizeOnDisk"\s+"(\d+)"')


def _manual_pick(pick: dict[str, Any]) -> dict[str, object]:
    """One contract ``ManualPickInfo`` from a ``status_payload`` pick."""
    age = pick.get("age_days")
    return {
        "app_id": pick["app_id"],
        "name": pick.get("game_name") or str(pick["app_id"]),
        # None means "start time unknown"; the contract field is a number.
        "age_days": round(float(age), 1) if age is not None else 0.0,
    }


def status_view(_request: Request) -> Reply:
    """``GET /api/status`` — the ``status`` command as ``StatusPayload``."""
    payload = status_payload(State.load())
    payload["assigned_game_installed"] = bool(payload["assigned_game_installed"])
    payload["manual_picks"] = [_manual_pick(p) for p in payload["manual_picks"]]
    return ok(payload)


def stats_view(_request: Request) -> Reply:
    """``GET /api/stats`` — the MCP ``get_stats`` projection of the dataset.

    Not imported from ``_mcp_query``: that pulls in the MCP server itself.
    """
    payload = dataset_to_payload(build_web_dataset(State.load()))
    return ok(
        {
            "default_summary": payload["default_summary"],
            "pace_vs_hltb": payload["pace_vs_hltb"],
        }
    )


def _size_on_disk(app_id: int) -> int:
    """``SizeOnDisk`` from the game's appmanifest (0 when unknown)."""
    # Through the module: tests redirect the path after import.
    manifest = _steam_state.STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    with contextlib.suppress(OSError):
        match = _SIZE_ON_DISK.search(manifest.read_text(encoding="utf-8"))
        if match:
            return int(match.group(1))
    return 0


def installed_view(_request: Request) -> Reply:
    """``GET /api/installed`` — what ``installed`` lists, with sizes.

    ``assigned`` covers every game the enforcer lets exist (the assignment
    and active manual picks), the set the uninstaller spares.
    """
    allowed = allowed_app_ids(State.load())
    games = [
        {
            "app_id": app_id,
            "name": name,
            "size_bytes": _size_on_disk(app_id),
            "assigned": app_id in allowed,
            "protected": is_protected_app(app_id),
        }
        for app_id, name in get_installed_games()
    ]
    return ok({"games": games})


def commands_view(_request: Request) -> Reply:
    """``GET /api/commands`` — the catalog, locks evaluated now."""
    return ok(command_specs())


def setup_view(_request: Request) -> Reply:
    """``GET /api/setup`` — configured flags; the API key is never returned."""
    return ok(setup_status(Config.load()))


def setup_status(config: Config) -> dict[str, object]:
    """The contract ``SetupStatus`` for *config*."""
    return {
        "configured": bool(config.steam_api_key and config.steam_id),
        "has_api_key": bool(config.steam_api_key),
        "steam_id": config.steam_id or None,
    }


def backups_view(_request: Request) -> Reply:
    """``GET /api/backups`` — every state backup, newest first."""
    return ok([backup.to_json() for backup in list_backups()])


def dataset_view(_request: Request) -> Reply:
    """``GET /api/dataset`` — the projected backlog dataset."""
    return ok(dataset_to_payload(build_web_dataset(State.load())))


def budget_view(request: Request) -> Reply:
    """``GET /api/budget`` — the gaming-budget snapshot.

    ``?demo=1`` reads the demo run's state and log, which is how the
    60-second demo can be watched hitting its cutoff in the browser without
    spending a real day's budget to see it.
    """
    return ok(build_budget_snapshot(demo=request.query.get("demo") == "1"))
