"""Tests for _own_pick: choosing your own next game outside the ranked list."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _own_pick
from steam_backlog_enforcer._own_pick import _eligible, _label, _matches
from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.tests._fake_prompter import FakePicker, FakePrompter

_PKG = "steam_backlog_enforcer._own_pick"
_UNTIL = datetime(2099, 1, 2, 3, 4, tzinfo=UTC).isoformat()


def _game(
    app_id: int, name: str = "G", *, unlocked: int = 5, hours: float = -1
) -> GameInfo:
    """Build an owned game with 10 achievements."""
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=10,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
    )


def _skipping(app_id: int) -> State:
    """Build a state that skips ``app_id`` until a far-future date."""
    return State(skipped_until={str(app_id): _UNTIL})


class TestIneligibleReason:
    """Why a game cannot be picked as your own next game."""

    def _reason(self, game: GameInfo | None, state: State | None = None) -> str | None:
        """Return the ineligible reason for app 7 under ``state``."""
        state = state or State()
        return _own_pick.ineligible_reason(7, game, state, state.active_skipped_ids())

    def test_no_scan_data(self) -> None:
        """A game with no scan data is refused for missing achievements."""
        assert self._reason(None) == "No achievement data"

    def test_complete_game(self) -> None:
        """A 100% game is refused as already complete."""
        assert self._reason(_game(7, unlocked=10)) == "Already 100% complete"

    def test_game_marked_finished_below_100(self) -> None:
        """A game marked finished is refused even below 100%."""
        state = State(finished_app_ids=[7])
        assert self._reason(_game(7), state) == "Marked finished"

    def test_skipped_game_names_the_date(self) -> None:
        """A skipped game names the day its skip ends."""
        assert self._reason(_game(7), _skipping(7)) == "Skipped until 2099-01-02"

    def test_skipped_game_without_a_date(self) -> None:
        """A skip with no stored end date reads as skipped for now."""
        reason = _own_pick.ineligible_reason(7, _game(7), State(), {7})
        assert reason == "Skipped for now"

    def test_unfinished_game_is_eligible(self) -> None:
        """An unfinished, unskipped game has no reason against it."""
        assert self._reason(_game(7)) is None


class TestMatching:
    """Finding owned games by a typed query."""

    def test_digits_match_the_exact_app_id(self) -> None:
        """A numeric query matches only the exact app id."""
        games = [_game(10, "Ten"), _game(100, "Hundred")]
        assert [g.app_id for g in _matches("10", games)] == [10]

    def test_names_match_by_substring_prefix_first(self) -> None:
        """Name matches are case-insensitive substrings, prefix hits first."""
        games = [_game(1, "The Doom"), _game(2, "Doom Eternal"), _game(3, "Quake")]
        hits = _matches("doom", games)
        assert [g.name for g in hits] == ["Doom Eternal", "The Doom"]

    def test_eligible_drops_complete_and_cooling_down_games(self) -> None:
        """Complete and skipped games are filtered out."""
        games = [_game(1), _game(2, unlocked=10), _game(3)]
        assert [g.app_id for g in _eligible(games, _skipping(3))] == [1]


class TestLabel:
    """How a game is shown as a choice."""

    def test_with_hours(self) -> None:
        """The label shows name and app id; the detail adds hours when known."""
        option = _label(_game(5, "Five", hours=2.5))
        assert option.value == "5"
        assert option.label == "Five (AppID=5)"
        assert option.detail == "50% achievements, ~2.5h"

    def test_without_hours(self) -> None:
        """Without an hours estimate the detail shows progress only."""
        assert _label(_game(5)).detail == "50% achievements"


class TestPromptOwnPickWithTextSearch:
    """The CLI path: no library browser, a typed search."""

    said: list[str]

    def _run(self, prompter: FakePrompter, games: list[GameInfo]) -> GameInfo | None:
        """Run the prompt, record what it echoed and return the pick."""
        with use_prompter(prompter), patch(f"{_PKG}._echo") as echo:
            self.said = [c.args[0] for c in echo.call_args_list]
            result = _own_pick.prompt_own_pick(games, State())
            self.said = [c.args[0] for c in echo.call_args_list]
        return result

    def test_empty_search_goes_back(self) -> None:
        """An empty search returns no pick."""
        assert self._run(FakePrompter(texts=[""]), [_game(1)]) is None

    def test_a_single_hit_is_taken_without_asking(self) -> None:
        """One match is returned after just the search prompt."""
        prompter = FakePrompter(texts=["quake"])
        games = [_game(1, "Quake"), _game(2, "Doom")]
        assert self._run(prompter, games) is games[0]
        assert len(prompter.asked) == 1

    def test_no_hits_searches_again(self) -> None:
        """No match says so and searches again."""
        prompter = FakePrompter(texts=["zzz", ""])
        assert self._run(prompter, [_game(1, "Quake")]) is None
        assert self.said == ["No unfinished owned game matches 'zzz'."]

    def test_too_many_hits_asks_to_narrow(self) -> None:
        """More than 15 matches asks for a longer query."""
        games = [_game(i, f"Game {i}") for i in range(1, 17)]
        assert self._run(FakePrompter(texts=["game", ""]), games) is None
        assert self.said == ["16 games match 'game'; type more of the name."]

    def test_several_hits_ask_which_one(self) -> None:
        """Several matches are offered with a search-again option."""
        games = [_game(1, "Doom"), _game(2, "Doom 2")]
        prompter = FakePrompter(texts=["doom"], choices=["2"])
        assert self._run(prompter, games) is games[1]
        assert prompter.asked[1][1] == ["1", "2", "search-again"]

    def test_search_again_restarts_the_search(self) -> None:
        """Choosing search-again goes back to the search prompt."""
        games = [_game(1, "Doom"), _game(2, "Doom 2")]
        prompter = FakePrompter(texts=["doom", ""], choices=["search-again"])
        assert self._run(prompter, games) is None

    def test_finished_games_are_not_offered(self) -> None:
        """A query matching only finished games finds nothing."""
        prompter = FakePrompter(texts=["done", ""])
        assert self._run(prompter, [_game(1, "Done", unlocked=10)]) is None
        assert self.said


class TestPromptOwnPickWithLibraryPicker:
    """The web path: the whole eligible library is shown at once."""

    def test_offers_only_eligible_games_and_returns_the_pick(self) -> None:
        """The picker sees only eligible games and its pick is returned."""
        games = [_game(1), _game(2, unlocked=10), _game(3)]
        picker = FakePicker(picks=[3])
        with use_prompter(picker):
            assert _own_pick.prompt_own_pick(games, State()) is games[2]
        assert picker.offered == [[1, 3]]

    @pytest.mark.parametrize("pick", [None, 2])
    def test_no_pick_or_an_ineligible_one_goes_back(self, pick: int | None) -> None:
        """No pick, or a pick of an ineligible game, returns nothing."""
        games = [_game(1), _game(2, unlocked=10)]
        with use_prompter(FakePicker(picks=[pick])):
            assert _own_pick.prompt_own_pick(games, State()) is None


def test_skip_expiry_is_judged_now() -> None:
    """An expired skip no longer makes the game ineligible."""
    expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    state = State(skipped_until={"1": expired})
    assert _eligible([_game(1)], state)[0].app_id == 1
