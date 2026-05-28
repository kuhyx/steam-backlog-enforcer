"""Tests for scanning module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.scanning import (
    _pick_playable_candidate,
    do_scan,
    pick_next_game,
)
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from collections.abc import Callable


def _game(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=3,
        count_comp=15,
    )


class TestDoScan:
    """Tests for do_scan."""

    def test_scans_and_picks(self) -> None:
        game = _game(app_id=440, name="TF2", total=10, unlocked=5)
        mock_client = MagicMock()

        def build_game_list(
            progress_callback: Callable[..., object] | None = None,
        ) -> list[GameInfo]:
            # Trigger progress callback to cover those lines.
            if progress_callback:
                progress_callback(50, 100)
                progress_callback(100, 100)
            return [game]

        mock_client.build_game_list.side_effect = build_game_list
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "steam_backlog_enforcer.scanning.fetch_hltb_times_cached",
                side_effect=lambda _games, progress_cb=None: (
                    progress_cb(1, 1, 1, "TF2") if progress_cb else None,
                    {440: 20.0},
                )[1],
            ),
            patch(
                "steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch(
                "steam_backlog_enforcer.scanning._echo",
            ),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_called_once()

    def test_scan_all_complete(self) -> None:
        game = _game(app_id=440, name="TF2", total=10, unlocked=10)
        mock_client = MagicMock()

        def build_game_list(
            progress_callback: Callable[..., object] | None = None,
        ) -> list[GameInfo]:
            if progress_callback:
                # current=1, total=2 → not %50 and not ==total → covers False branch
                progress_callback(1, 2)
            return [game]

        mock_client.build_game_list.side_effect = build_game_list
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_called_once()

    def test_scan_already_assigned(self) -> None:
        game = _game(app_id=440, total=10, unlocked=5)
        mock_client = MagicMock()
        mock_client.build_game_list.return_value = [game]
        with (
            patch(
                "steam_backlog_enforcer.scanning.SteamAPIClient",
                return_value=mock_client,
            ),
            patch(
                "steam_backlog_enforcer.scanning.fetch_hltb_times_cached",
                return_value={440: 20.0},
            ),
            patch(
                "steam_backlog_enforcer.scanning.save_snapshot",
            ),
            patch(
                "steam_backlog_enforcer.scanning.pick_next_game",
            ) as mock_pick,
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State(current_app_id=440)
            result = do_scan(config, state)
            assert len(result) == 1
            mock_pick.assert_not_called()


class TestPickPlayableCandidate:
    """Tests for _pick_playable_candidate."""

    def test_finds_playable(self) -> None:
        game = _game(app_id=440, name="TF2")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    440: ProtonDBRating(app_id=440, tier="gold"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([game])
            assert result is not None
            assert result.app_id == 440

    def test_skips_bad_rating(self) -> None:
        bad = _game(app_id=1, name="Bad")
        good = _game(app_id=2, name="Good")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    1: ProtonDBRating(app_id=1, tier="borked"),
                    2: ProtonDBRating(app_id=2, tier="platinum"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([bad, good])
            assert result is not None
            assert result.app_id == 2

    def test_all_unplayable(self) -> None:
        game = _game(app_id=1, name="Bad")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    1: ProtonDBRating(app_id=1, tier="borked"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            assert _pick_playable_candidate([game]) is None

    def test_empty_list(self) -> None:
        assert _pick_playable_candidate([]) is None

    def test_first_in_batch_playable(self) -> None:
        """First game in first batch is playable — no skip message."""
        game = _game(app_id=440, name="TF2")
        with (
            patch(
                "steam_backlog_enforcer.scanning.fetch_protondb_ratings",
                return_value={
                    440: ProtonDBRating(app_id=440, tier="platinum"),
                },
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            result = _pick_playable_candidate([game])
            assert result is not None


class TestPickNextGame:
    """Tests for pick_next_game."""

    def test_picks_shortest(self) -> None:
        g1 = _game(app_id=1, name="Long", hours=100.0)
        g2 = _game(app_id=2, name="Short", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer._scanning_confidence._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_no_candidates(self) -> None:
        g1 = _game(app_id=1, total=5, unlocked=5)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with patch("steam_backlog_enforcer.scanning._echo"):
            pick_next_game([g1], state, config)
            assert state.current_app_id is None

    def test_skips_finished(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=10.0)
        g2 = _game(app_id=2, name="G2", hours=20.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State(finished_app_ids=[1])
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_no_playable(self) -> None:
        g1 = _game(app_id=1, name="G1")
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id is None

    def test_uninstalls_others(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i", uninstall_other_games=True)
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer._scanning_confidence._echo"),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=2,
            ),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_auto_installs(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i", uninstall_other_games=False)
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch("steam_backlog_enforcer._scanning_confidence._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=False,
            ),
            patch("steam_backlog_enforcer.scanning.install_game") as mock_install,
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1], state, config)
            mock_install.assert_called_once()

    def test_unknown_hours(self) -> None:
        g1 = _game(app_id=1, name="G1", hours=-1)
        g2 = _game(app_id=2, name="G2", hours=10.0)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1, g2], state, config)
            assert state.current_app_id == 2

    def test_picks_game_no_hours(self) -> None:
        """Chosen game has no HLTB hours — covers no-hours output branch."""
        g1 = _game(app_id=1, name="G1", hours=-1)
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch("steam_backlog_enforcer.scanning._echo"),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([g1], state, config)
            assert state.current_app_id == 1

    def test_skips_low_confidence_and_picks_next(self) -> None:
        low = _game(app_id=1, name="LowConfidence", hours=1.0)
        low.comp_100_count = 1
        low.count_comp = 5
        valid = _game(app_id=2, name="ValidConfidence", hours=2.0)
        valid.comp_100_count = 3
        valid.count_comp = 15
        echoed: list[str] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                side_effect=lambda c: c[0] if c else None,
            ),
            patch(
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer.scanning.is_game_installed",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.scanning.uninstall_other_games",
                return_value=0,
            ),
            patch("builtins.input", return_value="1"),
        ):
            pick_next_game([low, valid], state, config)
        assert state.current_app_id == 2
        assert any("Skipping LowConfidence" in line for line in echoed)
        assert any("comp_100 polls 1 < 3" in line for line in echoed)

    def test_all_candidates_filtered_by_confidence(self) -> None:
        low_a = _game(app_id=1, name="LowA", hours=1.0)
        low_a.comp_100_count = 2
        low_a.count_comp = 15
        low_b = _game(app_id=2, name="LowB", hours=2.0)
        low_b.comp_100_count = 3
        low_b.count_comp = 14
        echoed: list[str] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()
        with (
            patch(
                "steam_backlog_enforcer.scanning._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer._scanning_confidence._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch(
                "steam_backlog_enforcer.scanning._pick_playable_candidate",
                return_value=None,
            ) as mock_pick,
        ):
            pick_next_game([low_a, low_b], state, config)
        assert state.current_app_id is None
        mock_pick.assert_not_called()
        assert any("No assignable games found" in line for line in echoed)
