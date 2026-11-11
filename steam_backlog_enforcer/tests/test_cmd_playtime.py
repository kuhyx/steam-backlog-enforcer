"""Tests for the daily-gaming-budget CLI handlers."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._cmd_playtime import (
    cmd_enforce,
    cmd_gaming_reset,
    cmd_gaming_status,
)
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    save_state,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._cmd_playtime_patches import cli_as, echoed
from steam_backlog_enforcer.tests._no_workout_http import fixed_budget

RESET_PKG = "steam_backlog_enforcer._gaming_reset"
_RESET_PHRASE = "reset today's gaming budget"
PKG = "steam_backlog_enforcer._cmd_playtime"


class TestCmdEnforce:
    """``enforce`` runs the real loop or, with --demo, the budget-only demo."""

    def test_runs_in_production_by_default(self) -> None:
        """Without flags the production enforce loop runs."""
        with (
            patch(f"{PKG}.do_enforce") as mock_run,
            patch(f"{PKG}.run_demo") as mock_demo,
            patch(f"{PKG}._echo"),
        ):
            assert cmd_enforce(Config(), State(), []) == 0
        mock_run.assert_called_once()
        mock_demo.assert_not_called()

    def test_demo_flag_runs_the_budget_only_demo(self) -> None:
        """--demo runs the demo instead of the production loop."""
        with (
            patch(f"{PKG}.do_enforce") as mock_run,
            patch(f"{PKG}.run_demo", return_value=0) as mock_demo,
        ):
            assert cmd_enforce(Config(), State(), ["--demo"]) == 0
        mock_demo.assert_called_once()
        mock_run.assert_not_called()

    def test_demo_exit_code_is_passed_on(self) -> None:
        """The demo's exit code is returned unchanged."""
        with patch(f"{PKG}.run_demo", return_value=1):
            assert cmd_enforce(Config(), State(), ["--demo"]) == 1

    def test_unknown_flag_exits_nonzero_without_running(self) -> None:
        """A mistyped --Demo must not silently run the real 8-hour budget."""
        with patch(f"{PKG}.do_enforce") as mock_run, patch(f"{PKG}._echo") as mock_echo:
            assert cmd_enforce(Config(), State(), ["--Demo"]) == 2
        mock_run.assert_not_called()
        assert "Unknown argument" in echoed(mock_echo)

    def test_unknown_flag_alongside_demo_still_rejected(self) -> None:
        """An unknown flag is rejected even next to --demo."""
        with patch(f"{PKG}.do_enforce") as mock_run, patch(f"{PKG}._echo"):
            assert cmd_enforce(Config(), State(), ["--demo", "--bogus"]) == 2
        mock_run.assert_not_called()


class TestCmdGamingStatus:
    """gaming-status reports today's budget, demo budget and masks."""

    def test_reports_no_state_yet(self) -> None:
        """With no saved state the status says so."""
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "no state recorded yet" in echoed(mock_echo)

    def test_reports_usage_and_remaining(self) -> None:
        """Usage and remaining budget are both reported."""
        save_state(PlaytimeState(day_key="2026-07-27", seconds=100.0), demo=False)
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
            fixed_budget(500.0),
        ):
            cmd_gaming_status(Config(), State())
        output = echoed(mock_echo)
        assert "used:" in output
        assert "100s" in output
        assert "400s" in output

    def test_hides_the_demo_section_when_unused(self) -> None:
        """The demo section is hidden when the demo was never used."""
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "Demo budget" not in echoed(mock_echo)

    def test_shows_the_demo_section_when_present(self) -> None:
        """The demo section appears once demo state exists."""
        save_state(PlaytimeState(day_key="2026-07-27", seconds=5.0), demo=True)
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "Demo budget" in echoed(mock_echo)

    def test_lists_masked_launchers(self) -> None:
        """Masked launchers are counted and listed."""
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}),
        ):
            cmd_gaming_status(Config(), State())
        output = echoed(mock_echo)
        assert "1/4" in output
        assert "/usr/bin/steam" in output

    def test_reports_blocked_flag(self) -> None:
        """A blocked day reports the blocked flag."""
        save_state(
            PlaytimeState(day_key="2026-07-27", seconds=1.0, blocked_at=5.0),
            demo=False,
        )
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.mounted_targets", return_value=set()),
        ):
            cmd_gaming_status(Config(), State())
        assert "blocked:        True" in echoed(mock_echo)


class TestCmdGamingReset:
    """gaming-reset clears today's counter only for root with the phrase."""

    def test_requires_root(self) -> None:
        """Without root nothing is reset."""
        with cli_as(1000) as mocks:
            assert cmd_gaming_reset(Config(), State()) == 1
        mocks.release.assert_not_called()
        assert "requires root" in echoed(mocks.echo)

    def test_aborts_without_the_typed_confirmation(self) -> None:
        """Anything but the exact phrase aborts the reset."""
        with cli_as(0) as mocks, patch("builtins.input", return_value="yes"):
            assert cmd_gaming_reset(Config(), State()) == 1
        mocks.release.assert_not_called()
        assert "Aborted" in echoed(mocks.echo)

    def test_resets_counter_and_releases_mounts(self) -> None:
        """The reset zeroes the counter and clears the block."""
        save_state(
            PlaytimeState(day_key="2026-07-26", seconds=999.0, blocked_at=5.0),
            demo=False,
        )
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value=_RESET_PHRASE),
            patch(f"{RESET_PKG}.release_block", return_value=["/usr/bin/steam"]),
        ):
            assert cmd_gaming_reset(Config(), State()) == 0
        stored = load_state(demo=False)
        assert stored.seconds == 0.0
        assert stored.is_blocked() is False

    def test_reports_how_many_mounts_were_released(self) -> None:
        """The reset reports how many mounts it released."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value=_RESET_PHRASE),
            patch(f"{RESET_PKG}.release_block", return_value=["/a", "/b"]),
        ):
            cmd_gaming_reset(Config(), State())
        assert "Released 2 mount(s)" in echoed(mock_echo)
