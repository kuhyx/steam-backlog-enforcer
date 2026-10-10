"""Tests for main._gate: the CLI's printing, exiting half of the lock gate."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import _gate

_PKG = "steam_backlog_enforcer.main._gate"
_CONFIGURED = Config(steam_api_key="k", steam_id="i")


class TestEnforceGate:
    def test_unconfigured_prints_and_exits(self) -> None:
        with patch(f"{_PKG}._echo") as echo, pytest.raises(SystemExit) as exc:
            _gate.enforce_gate("status", Config())
        assert exc.value.code == 1
        echo.assert_called_once_with(_gate.NOT_CONFIGURED_MSG)

    def test_passes_through_the_loaded_state(self) -> None:
        state = State(current_app_id=5)
        with (
            patch.object(State, "load", return_value=state),
            patch(f"{_PKG}._enforce_total_block_lock") as total,
            patch(f"{_PKG}._enforce_manual_pick_lock") as pick,
        ):
            assert _gate.enforce_gate("scan", _CONFIGURED) is state
        total.assert_called_once_with("scan")
        pick.assert_called_once_with("scan", state)

    def test_setup_runs_without_a_key(self) -> None:
        with (
            patch.object(State, "load", return_value=State()),
            patch(f"{_PKG}._enforce_total_block_lock"),
            patch(f"{_PKG}._enforce_manual_pick_lock"),
        ):
            assert isinstance(_gate.enforce_gate("setup", Config()), State)
