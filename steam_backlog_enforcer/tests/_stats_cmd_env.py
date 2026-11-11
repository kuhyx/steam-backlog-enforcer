"""Shared snapshot builders and the patch set the ``cmd_stats`` tests run under."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._stats import _GameTimes
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.tests._scanning_games import echo_into

if TYPE_CHECKING:
    from collections.abc import Iterator

STATS = "steam_backlog_enforcer._stats"


def stats_config() -> Config:
    """Build the minimal Config cmd_stats runs against."""
    return Config(steam_api_key="k", steam_id="i")


def snapshot_game(app_id: int = 1, hours: float = 20.0) -> dict[str, object]:
    """Build one unstarted, confidently-timed game as stored in the snapshot."""
    return {
        "app_id": app_id,
        "name": f"Game{app_id}",
        "total_achievements": 10,
        "unlocked_achievements": 0,
        "playtime_minutes": 60,
        "completionist_hours": hours,
        "comp_100_count": 5,
        "count_comp": 20,
    }


def times_entry(
    snapshot: dict[str, object], rush: float = 15.0, leisure: float = 25.0
) -> _GameTimes:
    """Wrap a snapshot game as a qualifying entry worth 20 h worst-case."""
    return _GameTimes(
        game=GameInfo.from_snapshot(snapshot),
        worst_hours=20.0,
        rush_hours=rush,
        leisure_100h=leisure,
    )


@contextmanager
def cmd_stats_env(
    snapshot: list[dict[str, object]],
    filtered: object,
    echoed: list[str] | None = None,
    **extra: dict[str, object],
) -> Iterator[None]:
    """Patch cmd_stats's collaborators around ``snapshot``.

    ``filtered`` is what ``_filter_qualifying_games`` returns, or a callable
    used as its side effect. ``_echo`` records into ``echoed`` when given.
    Each ``extra`` item patches ``_stats.<name>`` with those keyword arguments,
    replacing the default patch of the same name.
    """
    key = "side_effect" if callable(filtered) else "return_value"
    patches: dict[str, dict[str, object]] = {
        "_filter_qualifying_games": {key: filtered},
        "_ensure_completed_rush_data": {"return_value": False},
        "_print_player_speed_scenario": {},
        "_echo": {} if echoed is None else {"side_effect": echo_into(echoed)},
        "_print_pace_scenario": {},
        "_print_scenario": {},
    }
    patches.update(extra)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "steam_backlog_enforcer._snapshot.load_snapshot", return_value=snapshot
            )
        )
        for name, kwargs in patches.items():
            stack.enter_context(patch(f"{STATS}.{name}", **kwargs))
        yield
