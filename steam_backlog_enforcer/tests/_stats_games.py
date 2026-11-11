"""Shared game and rating builders for the ``_stats`` tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._stats import _filter_qualifying_games
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.tests._scanning_games import (
    make_game as make_scanning_game,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from unittest.mock import MagicMock

    from steam_backlog_enforcer._stats import _GameTimes
    from steam_backlog_enforcer.config import State
    from steam_backlog_enforcer.steam_api import GameInfo

_GATHER = "steam_backlog_enforcer._stats_gathering"


def make_game(
    app_id: int = 1,
    name: str = "G",
    hours: float = 10.0,
    total: int = 10,
    unlocked: int = 0,
) -> GameInfo:
    """Build a game with confident HLTB data (5 polls, 20 runs)."""
    game = make_scanning_game(app_id, name, total, unlocked, hours)
    game.comp_100_count = 5
    game.count_comp = 20
    return game


def unplayable_rating(app_id: int) -> ProtonDBRating:
    """Build a ProtonDB rating that marks the game unplayable on Linux."""
    return ProtonDBRating(app_id=app_id, tier="borked")


@dataclass
class FilterInputs:
    """What _filter_qualifying_games reads from the HLTB caches and ProtonDB."""

    rush_cache: dict[int, float] = field(default_factory=dict)
    leisure_cache: dict[int, float] = field(default_factory=dict)
    game_id_cache: dict[int, int] = field(default_factory=dict)
    fail_reasons: list[str] = field(default_factory=list)
    ratings: dict[int, ProtonDBRating] = field(default_factory=dict)


@contextmanager
def filter_env(inputs: FilterInputs | None = None) -> Iterator[MagicMock]:
    """Feed _filter_qualifying_games ``inputs``; yield the ProtonDB fetch mock."""
    given = inputs or FilterInputs()
    with (
        patch(f"{_GATHER}.load_hltb_rush_cache", return_value=given.rush_cache),
        patch(
            f"{_GATHER}.load_hltb_leisure_100h_cache",
            return_value=given.leisure_cache,
        ),
        patch(f"{_GATHER}.load_hltb_game_id_cache", return_value=given.game_id_cache),
        patch(f"{_GATHER}._apply_cached_confidence_to_candidates"),
        patch(f"{_GATHER}._refresh_candidate_confidence_batch"),
        patch(f"{_GATHER}._confidence_fail_reasons", return_value=given.fail_reasons),
        patch(
            f"{_GATHER}.fetch_protondb_ratings", return_value=given.ratings
        ) as proton,
    ):
        yield proton


def run_filter(
    games: list[GameInfo], state: State, inputs: FilterInputs | None = None
) -> tuple[list[_GameTimes], int, int, int]:
    """Run _filter_qualifying_games under :func:`filter_env`."""
    with filter_env(inputs):
        return _filter_qualifying_games(games, state)
