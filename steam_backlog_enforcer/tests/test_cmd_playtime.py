"""Tests for the daily-gaming-budget CLI handlers."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._cmd_playtime import (
    cmd_enforce,
    cmd_gaming_reset,
    cmd_gaming_status,
    cmd_gaming_unblock,
)
from steam_backlog_enforcer._playtime import PlaytimeState, load_state, save_state
from steam_backlog_enforcer.config import Config, State

PKG = "steam_backlog_enforcer._cmd_playtime"


def _echoed(mock_echo: object) -> str:
    return " ".join(str(c) for c in mock_echo.call_args_list)


class TestCmdEnforce:
    def test_runs_in_production_by_default(self) -> None:
        with patch(f"{PKG}.do_enforce") as mock_run, patch(f"{PKG}._echo"):
            assert cmd_enforce(Config(), State(), []) == 0
        assert mock_run.call_args.kwargs["demo"] is False

    def test_demo_flag_enables_demo(self) -> None:
        with patch(f"{PKG}.do_enforce") as mock_run, patch(f"{PKG}._echo"):
            assert cmd_enforce(Config(), State(), ["--demo"]) == 0
        assert mock_run.call_args.kwargs["demo"] is True

    def test_demo_announces_itself(self) -> None:
        with patch(f"{PKG}.do_enforce"), patch(f"{PKG}._echo") as mock_echo:
            cmd_enforce(Config(), State(), ["--demo"])
        assert "DEMO MODE" in _echoed(mock_echo)

    def test_unknown_flag_exits_nonzero_without_running(self) -> None:
        """A mistyped --Demo must not silently run the real 8-hour budget."""
        with patch(f"{PKG}.do_enforce") as mock_run, patch(f"{PKG}._echo") as mock_echo:
            assert cmd_enforce(Config(), State(), ["--Demo"]) == 2
        mock_run.assert_not_called()
        assert "Unknown argument" in _echoed(mock_echo)

    def test_unknown_flag_alongside_demo_still_rejected(self) -> None:
        with patch(f"{PKG}.do_enforce") as mock_run, patch(f"{PKG}._echo"):
            assert cmd_enforce(Config(), State(), ["--demo", "--bogus"]) == 2
        mock_run.assert_not_called()


class TestCmdGamingStatus:
    def test_reports_no_state_yet(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "no state recorded yet" in _echoed(mock_echo)

    def test_reports_usage_and_remaining(self) -> None:
        save_state(PlaytimeState(day_key="2026-07-27", seconds=100.0), demo=False)
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(daily_gaming_seconds=500), State())
        output = _echoed(mock_echo)
        assert "used:" in output
        assert "100s" in output
        assert "400s" in output

    def test_hides_the_demo_section_when_unused(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "Demo budget" not in _echoed(mock_echo)

    def test_shows_the_demo_section_when_present(self) -> None:
        save_state(PlaytimeState(day_key="2026-07-27", seconds=5.0), demo=True)
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "Demo budget" in _echoed(mock_echo)

    def test_lists_masked_launchers(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}),
        ):
            cmd_gaming_status(Config(), State())
        output = _echoed(mock_echo)
        assert "1/4" in output
        assert "/usr/bin/steam" in output

    def test_reports_blocked_flag(self) -> None:
        save_state(
            PlaytimeState(day_key="2026-07-27", seconds=1.0, blocked_at=5.0),
            demo=False,
        )
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "blocked:        True" in _echoed(mock_echo)


class TestCmdGamingReset:
    def test_requires_root(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.release_block") as mock_release,
        ):
            assert cmd_gaming_reset(Config(), State()) == 1
        mock_release.assert_not_called()
        assert "requires root" in _echoed(mock_echo)

    def test_aborts_without_the_typed_confirmation(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="yes"),
            patch(f"{PKG}.release_block") as mock_release,
        ):
            assert cmd_gaming_reset(Config(), State()) == 1
        mock_release.assert_not_called()
        assert "Aborted" in _echoed(mock_echo)

    def test_resets_counter_and_releases_mounts(self) -> None:
        save_state(
            PlaytimeState(day_key="2026-07-26", seconds=999.0, blocked_at=5.0),
            demo=False,
        )
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.release_block", return_value=["/usr/bin/steam"]),
        ):
            assert cmd_gaming_reset(Config(), State()) == 0
        stored = load_state(demo=False)
        assert stored.seconds == 0.0
        assert stored.is_blocked() is False

    def test_reports_how_many_mounts_were_released(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.release_block", return_value=["/a", "/b"]),
        ):
            cmd_gaming_reset(Config(), State())
        assert "Released 2 mount(s)" in _echoed(mock_echo)


class TestCmdGamingUnblock:
    def test_rejects_arguments(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.release_block") as mock_release,
        ):
            assert cmd_gaming_unblock(["--force"]) == 2
        mock_release.assert_not_called()
        assert "Unknown argument" in _echoed(mock_echo)

    def test_requires_root(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=1000),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.release_block") as mock_release,
        ):
            assert cmd_gaming_unblock([]) == 1
        mock_release.assert_not_called()
        assert "requires root" in _echoed(mock_echo)

    def test_reports_when_nothing_was_mounted(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.release_block", return_value=[]),
        ):
            assert cmd_gaming_unblock([]) == 0
        assert "No playtime mounts" in _echoed(mock_echo)

    def test_lists_released_mounts(self) -> None:
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch(
                f"{PKG}.release_block",
                return_value=["/usr/bin/steam", "/usr/bin/lutris"],
            ),
        ):
            assert cmd_gaming_unblock([]) == 0
        output = _echoed(mock_echo)
        assert "/usr/bin/steam" in output
        assert "/usr/bin/lutris" in output

    def test_consults_no_state_at_all(self) -> None:
        """The recovery hatch must work with an unreadable state file."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo"),
            patch(
                f"{PKG}.load_state", side_effect=AssertionError("must not be called")
            ),
            patch(f"{PKG}.release_block", return_value=[]),
        ):
            assert cmd_gaming_unblock([]) == 0
