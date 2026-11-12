"""One daemon pass under a total block: the window and the full block."""

from __future__ import annotations

import subprocess

import pytest

from steam_backlog_enforcer import _research_record as store
from steam_backlog_enforcer import _research_window as window
from steam_backlog_enforcer import config as cfg
from steam_backlog_enforcer.tests._research_fixtures import Mocks, run_pass
from steam_backlog_enforcer.tests._research_helpers import HOUR, NOW, make_record


class TestFullBlock:
    """Without a live window the whole total block is enforced."""

    def test_no_record_runs_the_full_tick(self, tm: Mocks) -> None:
        """Test that the default is the full block."""
        run_pass()
        tm.block_tick.assert_called_once_with(keep_steam_dir=False)
        tm.reconcile.assert_not_called()
        tm.enforce.assert_not_called()

    def test_corrupt_record_runs_the_full_tick(self, tm: Mocks) -> None:
        """Test that unreadable research state means fully blocked."""
        store.RESEARCH_FILE.parent.mkdir(parents=True)
        store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
        run_pass()
        tm.block_tick.assert_called_once_with(keep_steam_dir=True)
        tm.reconcile.assert_not_called()

    def test_clock_before_opening_blocks_without_latching(self, tm: Mocks) -> None:
        """Test that a clock set back blocks, but does not burn the window."""
        window.write_record(make_record())
        run_pass(NOW - 3 * HOUR)
        tm.block_tick.assert_called_once_with(keep_steam_dir=True)
        tm.reconcile.assert_not_called()
        record = window.read_record()
        assert record is not None
        assert record.closed is False

    def test_latched_and_reblocked_record_only_runs_the_block(self, tm: Mocks) -> None:
        """Test that a finished window costs nothing but the block tick."""
        window.write_record(make_record(closed=True, store_reblocked=True))
        run_pass(NOW + 5 * HOUR)
        tm.block_tick.assert_called_once_with(keep_steam_dir=True)
        tm.restore_store.assert_not_called()


class TestOpenWindow:
    """Inside the window: Steam is left alone, everything but Librarian is not."""

    def test_extended_window_stays_open_past_its_first_deadline(
        self, tm: Mocks
    ) -> None:
        """Test that the extension keeps the research pass running."""
        window.write_record(make_record(extended_until=NOW + 9 * HOUR))
        run_pass(NOW + 4 * HOUR)
        tm.reconcile.assert_called_once()
        tm.block_tick.assert_not_called()

    def test_reconciles_and_skips_the_full_block(self, tm: Mocks) -> None:
        """Test that the open window replaces the block tick."""
        window.write_record(make_record())
        run_pass()
        tm.reconcile.assert_called_once_with(make_record())
        tm.block_tick.assert_not_called()

    def test_steam_is_never_killed_uninstalled_or_purged(self, tm: Mocks) -> None:
        """Test that the destructive half of the block stays off."""
        window.write_record(make_record())
        run_pass()
        tm.steam.kill.assert_not_called()
        tm.steam.uninstall.assert_not_called()
        tm.steam.purge.assert_not_called()

    def test_other_launchers_and_counted_games_are_still_killed(
        self, tm: Mocks
    ) -> None:
        """Test that non-Steam games stay forbidden during the window."""
        window.write_record(make_record())
        run_pass()
        tm.launchers.assert_called_once()
        tm.counted.assert_called_once()

    def test_only_librarian_is_allowed_and_strictly(self, tm: Mocks) -> None:
        """Test that the allowed set is exactly Librarian, no exceptions."""
        window.write_record(make_record())
        run_pass()
        tm.enforce.assert_called_once_with(
            {window.LIBRARIAN_APP_ID}, kill_unauthorized=True, strict=True
        )
        tm.guard.assert_called_once_with({window.LIBRARIAN_APP_ID}, strict=True)

    def test_killed_game_is_reported(self, tm: Mocks) -> None:
        """Test that a killed non-Librarian game raises a notification."""
        tm.enforce.return_value = [(4242, 12345)]
        window.write_record(make_record())
        run_pass()
        tm.notify.assert_called_once()

    def test_no_game_enforcement_while_steam_is_not_installed_yet(
        self, tm: Mocks
    ) -> None:
        """Test that the install gap does not scan an absent library."""
        tm.steam.installed.return_value = False
        window.write_record(make_record())
        run_pass()
        tm.enforce.assert_not_called()
        tm.guard.assert_not_called()

    def test_real_assignment_is_never_touched(self, tm: Mocks) -> None:
        """Test that state.json (the real backlog) is not read or written."""
        cfg.STATE_FILE.write_text('{"current_app_id": 1366540}', encoding="utf-8")
        before = cfg.STATE_FILE.read_bytes()
        window.write_record(make_record())
        run_pass()
        assert cfg.STATE_FILE.read_bytes() == before
        assert tm.enforce.call_args.args[0] == {window.LIBRARIAN_APP_ID}


class TestSlowSystem:
    """A command that times out costs one tick, never the daemon."""

    @pytest.mark.parametrize(
        "error",
        [subprocess.TimeoutExpired(["pacman", "-Qi", "steam"], 10), OSError("busy")],
    )
    def test_failed_reconcile_is_retried_next_tick(
        self, tm: Mocks, error: Exception
    ) -> None:
        """Test that a timed-out pacman/iptables call does not crash the loop."""
        tm.reconcile.side_effect = error
        window.write_record(make_record())
        run_pass()
        tm.block_tick.assert_not_called()
        tm.enforce.assert_not_called()
        tm.reconcile.side_effect = None
        run_pass()
        tm.enforce.assert_called_once()
