"""Shared builders and patches for the HLTB poll-count tracking tests."""

from __future__ import annotations

from contextlib import contextmanager
import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._cmd_done import _report_assigned_confidence
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.scanning import _report_poll_confidence
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

TYPES = "steam_backlog_enforcer._hltb_types"
CMD = "steam_backlog_enforcer._cmd_done"
SCAN = "steam_backlog_enforcer.scanning"
SCANCONF = "steam_backlog_enforcer._scanning_confidence"
POLLS = "steam_backlog_enforcer._polls_reporting"
FETCH_CONFIDENCE = "steam_backlog_enforcer._hltb_confidence.fetch_hltb_confidence"


def poll_state(finished: list[int], current: int | None = None) -> State:
    """Return a state with the given finished games and current pick."""
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


def make_game(
    app_id: int,
    name: str,
    *,
    total: int = 10,
    unlocked: int = 0,
    polls: tuple[int, int] = (0, 0),
) -> GameInfo:
    """Return an unplayed GameInfo; ``polls`` is (comp_100_count, count_comp)."""
    comp_100_count, count_comp = polls
    return GameInfo(
        app_id,
        name,
        total,
        unlocked,
        playtime_minutes=0,
        comp_100_count=comp_100_count,
        count_comp=count_comp,
    )


def write_cache(tmp_path: Path, data: dict[str, object]) -> Path:
    """Write ``data`` as the HLTB cache file under ``tmp_path`` and return it."""
    cache_file = tmp_path / "hltb_cache.json"
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return cache_file


def filling_fetch(
    hours: float, polls_n: int, count_comp_n: int = 0
) -> Callable[..., list[object]]:
    """Return a fake HLTB search that writes the same row for every game asked."""

    def fake_fetch(
        games: list[tuple[int, str]],
        cache: dict[int, float],
        polls: dict[int, int],
        count_comp: dict[int, int],
        **_kw: object,
    ) -> list[object]:
        """Write into the caches it is handed."""
        for aid, _name in games:
            cache[aid], polls[aid], count_comp[aid] = hours, polls_n, count_comp_n
        return []

    return fake_fetch


@contextmanager
def hltb_cache_patched(
    cache_file: Path, tmp_path: Path, fetch: Callable[..., list[object]]
) -> Iterator[MagicMock]:
    """Point the HLTB cache at ``cache_file``; route confidence fetches to ``fetch``."""
    with (
        patch(f"{TYPES}.HLTB_CACHE_FILE", cache_file),
        patch(f"{TYPES}.CONFIG_DIR", tmp_path),
        patch(FETCH_CONFIDENCE, side_effect=fetch) as mock_fetch,
    ):
        yield mock_fetch


@contextmanager
def echo_sink(target: str, echoed: list[str]) -> Iterator[MagicMock]:
    """Patch ``target._echo`` so each echoed first arg lands in ``echoed``."""
    with patch(
        f"{target}._echo", side_effect=lambda *a, **_: echoed.append(a[0])
    ) as mock_echo:
        yield mock_echo


def poll_confidence_echoes(
    chosen: GameInfo, games: list[GameInfo], polls: dict[int, int], state: State
) -> list[str]:
    """Run ``_report_poll_confidence`` with backfilled ``polls``; return its echoes."""
    echoed: list[str] = []
    with (
        patch(f"{POLLS}._backfill_polls_for_finished", return_value=polls),
        echo_sink(POLLS, echoed),
    ):
        _report_poll_confidence(chosen, games, state)
    return echoed


def assigned_confidence_echoes(
    polls: dict[int, int], snapshot: list[dict[str, object]], state: State
) -> list[str]:
    """Run ``_report_assigned_confidence`` for app 1; return its echoes."""
    echoed: list[str] = []
    with (
        patch(f"{CMD}._backfill_polls_for_finished", return_value=polls),
        patch(f"{CMD}.load_snapshot", return_value=snapshot),
        echo_sink(CMD, echoed),
    ):
        _report_assigned_confidence(1, state)
    return echoed
