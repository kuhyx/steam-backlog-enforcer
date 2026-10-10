"""Tests for _command_gate: the lock rules shared by the CLI and web jobs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _command_gate as _gate
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._main_helpers import locked_state

if TYPE_CHECKING:
    from collections.abc import Iterator

_PKG = "steam_backlog_enforcer._command_gate"
_CONFIGURED = Config(steam_api_key="k", steam_id="i")


@contextmanager
def _block(*, active: bool, days: float = 3.5) -> Iterator[None]:
    """Patch the total-block status the gate reads."""
    status = MagicMock(days_remaining=days)
    with (
        patch(f"{_PKG}.is_total_block_active", return_value=active),
        patch(f"{_PKG}.get_total_block_status", return_value=status),
    ):
        yield


class TestLockReason:
    def test_unconfigured_is_refused(self) -> None:
        assert _gate.lock_reason("status", Config(), State()) == (
            _gate.NOT_CONFIGURED_MSG
        )

    @pytest.mark.parametrize("command", ["setup", "add-exception"])
    def test_setup_commands_need_no_key(self, command: str) -> None:
        with _block(active=False):
            assert _gate.lock_reason(command, Config(), State()) is None

    def test_total_block_names_days_and_allowed_commands(self) -> None:
        with _block(active=True):
            reason = _gate.lock_reason("scan", _CONFIGURED, State())
        assert reason is not None
        assert "Total gaming block active (3.5 day(s) left)" in reason
        assert "Allowed:" in reason

    def test_exempt_commands_pass_the_total_block(self) -> None:
        with _block(active=True):
            assert _gate.lock_reason("status", _CONFIGURED, State()) is None

    def test_manual_pick_lock_names_the_picks(self) -> None:
        with _block(active=False):
            reason = _gate.lock_reason("scan", _CONFIGURED, locked_state())
        assert reason is not None
        assert "Manual pick lock active (TestGame)" in reason

    def test_exempt_commands_pass_the_pick_lock(self) -> None:
        with _block(active=False):
            assert _gate.lock_reason("status", _CONFIGURED, locked_state()) is None

    def test_no_state_skips_the_pick_check(self) -> None:
        with _block(active=False):
            assert _gate.lock_reason("scan", _CONFIGURED, None) is None
