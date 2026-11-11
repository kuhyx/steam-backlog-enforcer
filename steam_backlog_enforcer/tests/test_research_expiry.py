"""The window's end: latch, full block back, store block back once."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _research_window as window
from steam_backlog_enforcer._research_net import RETRY_AFTER_SECONDS
from steam_backlog_enforcer.tests._research_fixtures import Mocks, run_pass
from steam_backlog_enforcer.tests._research_helpers import HOUR, NOW, make_record


class TestExpiry:
    """At the deadline the full block returns, once, and the window stays shut."""

    def test_expiry_latches_then_reapplies_the_full_block(self, tm: Mocks) -> None:
        """Test that a passed deadline closes the record and runs the block."""
        window.write_record(make_record())
        run_pass(NOW + 2 * HOUR)
        record = window.read_record()
        assert record is not None
        assert record.closed is True
        tm.block_tick.assert_called_once_with()
        tm.reconcile.assert_not_called()

    def test_store_is_reblocked_once(self, tm: Mocks) -> None:
        """Test that the normal store block returns once and is remembered."""
        window.write_record(make_record())
        run_pass(NOW + 2 * HOUR)
        tm.restore_store.assert_called_once_with()
        record = window.read_record()
        assert record is not None
        assert record.store_reblocked is True
        run_pass(NOW + 3 * HOUR)
        tm.restore_store.assert_called_once_with()

    def test_failed_store_reblock_is_retried_after_a_pause(self, tm: Mocks) -> None:
        """Test that the flag is only set once the store is really blocked."""
        clock = [1000.0]
        tm.restore_store.return_value = False
        window.write_record(make_record())
        with patch(
            "steam_backlog_enforcer._research_net.monotonic",
            side_effect=lambda: clock[0],
        ):
            run_pass(NOW + 2 * HOUR)
            record = window.read_record()
            assert record is not None
            assert record.store_reblocked is False
            run_pass(NOW + 2 * HOUR + 3)
            assert tm.restore_store.call_count == 1
            clock[0] += RETRY_AFTER_SECONDS + 1
            tm.restore_store.return_value = True
            run_pass(NOW + 2 * HOUR + 70)
        assert tm.restore_store.call_count == 2
        record = window.read_record()
        assert record is not None
        assert record.store_reblocked is True

    def test_store_not_managed_is_just_flagged(self, tm: Mocks) -> None:
        """Test that block_store=False in config leaves the store alone."""
        window.write_record(make_record())
        run_pass(NOW + 2 * HOUR, block_store=False)
        tm.restore_store.assert_not_called()
        record = window.read_record()
        assert record is not None
        assert record.store_reblocked is True

    def test_clock_rolled_back_after_expiry_cannot_reopen(self, tm: Mocks) -> None:
        """Test that the latch beats a clock set back into the old window."""
        window.write_record(make_record())
        run_pass(NOW + 2 * HOUR)
        tm.reconcile.reset_mock()
        run_pass(NOW)
        tm.reconcile.assert_not_called()

    def test_latch_write_failure_still_blocks(self, tm: Mocks) -> None:
        """Test that an unwritable record cannot keep the window open."""
        window.write_record(make_record())
        with patch.object(window, "write_record", side_effect=OSError("ro")):
            run_pass(NOW + 2 * HOUR)
        tm.block_tick.assert_called_once_with()
        tm.reconcile.assert_not_called()
