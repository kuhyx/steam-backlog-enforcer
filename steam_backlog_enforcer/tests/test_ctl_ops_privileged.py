"""Tests for the mutating ops in ``_ctl_ops``: store window, block, unblock.

Each op re-checks its phrase, bounds and the CLI's locks. The lock gate and
the privileged collaborators are mocked, so nothing here opens a store window,
engages a block or touches a mount.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_ops
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx

if TYPE_CHECKING:
    from collections.abc import Iterator

_UNTIL = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
_UNBLOCK_PHRASE = "unblock the store for 5 minutes"


@pytest.fixture(name="hand_back", autouse=True)
def fixture_hand_back() -> Iterator[MagicMock]:
    """The chown helper is covered elsewhere; keep it away from real paths."""
    with patch.object(_ctl_ops, "_hand_back_state_file") as helper:
        yield helper


class TestStoreUnblock:
    """store_unblock opens the timed store window."""

    def test_opens_window(self, hand_back: MagicMock) -> None:
        """The right phrase opens the window and hands the state file back."""
        ctx = make_ctx()
        with (
            patch.object(_ctl_ops, "check_locks") as locks,
            patch.object(_ctl_ops, "open_store_window", return_value=_UNTIL) as opened,
        ):
            data = _ctl_ops.op_store_unblock(
                ctx, {"minutes": 5, "phrase": _UNBLOCK_PHRASE}
            )
        assert data == {"minutes": 5, "until": _UNTIL.isoformat()}
        locks.assert_called_once_with("unblock")
        assert opened.call_args.args[1] == 5
        hand_back.assert_called_once()
        assert not ctx.tick_lock.locked()

    def test_wrong_phrase(self) -> None:
        """A wrong phrase refuses the store window."""
        with pytest.raises(CtlError) as caught:
            _ctl_ops.op_store_unblock(make_ctx(), {"minutes": 5, "phrase": "no"})
        assert caught.value.code == "wrong_phrase"

    def test_minutes_out_of_range(self) -> None:
        """Minutes outside the allowed range are refused as invalid_params."""
        with pytest.raises(CtlError) as caught:
            _ctl_ops.op_store_unblock(make_ctx(), {"minutes": 99, "phrase": "x"})
        assert caught.value.code == "invalid_params"

    def test_runtime_error_is_op_failed_and_still_hands_back(
        self, hand_back: MagicMock
    ) -> None:
        """A RuntimeError is op_failed and the state is still handed back."""
        with (
            patch.object(_ctl_ops, "check_locks"),
            patch.object(_ctl_ops, "open_store_window", side_effect=RuntimeError("x")),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_ops.op_store_unblock(
                make_ctx(), {"minutes": 5, "phrase": _UNBLOCK_PHRASE}
            )
        assert caught.value.code == "op_failed"
        hand_back.assert_called_once()

    def test_locked(self) -> None:
        """An active CLI lock refuses the store window."""
        lock = CtlError("locked", "a total gaming block is active")
        with (
            patch.object(_ctl_ops, "check_locks", side_effect=lock),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_ops.op_store_unblock(
                make_ctx(), {"minutes": 5, "phrase": _UNBLOCK_PHRASE}
            )
        assert caught.value.code == "locked"


class TestBlockGaming:
    """block_gaming starts the (irreversible) total block."""

    _ARGS: ClassVar[dict[str, object]] = {
        "days": 3,
        "phrase": "block all gaming for 3 days",
    }

    def test_starts_block(self) -> None:
        """The right phrase starts the block and reports its end time."""
        status = MagicMock(until=_UNTIL)
        with (
            patch.object(_ctl_ops, "check_locks") as locks,
            patch.object(_ctl_ops, "start_total_block", return_value=True) as start,
            patch.object(_ctl_ops, "get_total_block_status", return_value=status),
        ):
            data = _ctl_ops.op_block_gaming(make_ctx(), self._ARGS)
        assert data == {"days": 3, "until": _UNTIL.isoformat()}
        start.assert_called_once_with(3)
        locks.assert_called_once_with("block-gaming")

    def test_until_unknown(self) -> None:
        """A block without a known end reports until as None."""
        with (
            patch.object(_ctl_ops, "check_locks"),
            patch.object(_ctl_ops, "start_total_block", return_value=True),
            patch.object(
                _ctl_ops, "get_total_block_status", return_value=MagicMock(until=None)
            ),
        ):
            data = _ctl_ops.op_block_gaming(make_ctx(), self._ARGS)
        assert data["until"] is None

    def test_failure_is_op_failed(self) -> None:
        """A block that fails to start is op_failed."""
        with (
            patch.object(_ctl_ops, "check_locks"),
            patch.object(_ctl_ops, "start_total_block", return_value=False),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_ops.op_block_gaming(make_ctx(), self._ARGS)
        assert caught.value.code == "op_failed"

    def test_days_capped(self) -> None:
        """Days above MAX_BLOCK_DAYS are refused as invalid_params."""
        args = {"days": _ctl_ops.MAX_BLOCK_DAYS + 1, "phrase": "x"}
        with pytest.raises(CtlError) as caught:
            _ctl_ops.op_block_gaming(make_ctx(), args)
        assert caught.value.code == "invalid_params"


class TestGamingUnblock:
    """gaming_unblock releases every playtime mount."""

    def test_releases(self) -> None:
        """The right phrase releases the mounts and lists their paths."""
        with (
            patch.object(_ctl_ops, "check_locks") as locks,
            patch.object(
                _ctl_ops, "release_block", return_value=[Path("/a"), Path("/b")]
            ),
        ):
            data = _ctl_ops.op_gaming_unblock(
                make_ctx(), {"phrase": "force release playtime mounts"}
            )
        assert data == {"released": ["/a", "/b"]}
        locks.assert_called_once_with("gaming-unblock")

    def test_wrong_phrase(self) -> None:
        """A wrong phrase refuses the mount release."""
        with pytest.raises(CtlError) as caught:
            _ctl_ops.op_gaming_unblock(make_ctx(), {"phrase": ""})
        assert caught.value.code == "wrong_phrase"


class TestOpsTable:
    """The allowlist is exactly the documented ops."""

    def test_names(self) -> None:
        """The op table contains exactly the documented op names."""
        assert set(_ctl_ops.OPS) == {
            "ping",
            "status",
            "journal_tail",
            "store_unblock",
            "block_gaming",
            "gaming_unblock",
            "gaming_reset_arm",
            "gaming_reset_heartbeat",
            "gaming_reset_commit",
            "gaming_reset_cancel",
            "restart",
        }
