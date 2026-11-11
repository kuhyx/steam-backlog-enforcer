"""The `total-block-refresh` command: root-only, lock-exempt, fail-closed."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _cmd_total_block_refresh as cmd
from steam_backlog_enforcer._command_gate import UNCONFIGURED_OK
from steam_backlog_enforcer._command_help import ALL_COMMAND_DESCRIPTIONS
from steam_backlog_enforcer._command_locks import (
    _MANUAL_LOCK_EXEMPT_COMMANDS,
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

PKG = "steam_backlog_enforcer._cmd_total_block_refresh"
NAME = "total-block-refresh"


def _step(
    calls: list[str], name: str, *, result: bool | None
) -> Callable[[], bool | None]:
    """A stand-in step that logs its name and returns *result*."""

    def run() -> bool | None:
        calls.append(name)
        return result

    return run


@pytest.fixture(name="steps")
def _steps() -> Iterator[list[str]]:
    """Root, active block, every step succeeding; yields the call log."""
    calls: list[str] = []
    with (
        patch(f"{PKG}.os.geteuid", return_value=0),
        patch(f"{PKG}.is_total_block_active", return_value=True),
        patch(f"{PKG}.refresh_total_block_hosts", _step(calls, "hosts", result=True)),
        patch(f"{PKG}.flush_dns_cache", _step(calls, "flush", result=None)),
        patch(f"{PKG}.refresh_total_block_iptables", _step(calls, "ipt", result=True)),
    ):
        yield calls


class TestCmd:
    """Order, gating and failure behaviour."""

    def test_runs_hosts_then_flush_then_iptables(self, steps: list[str]) -> None:
        """Test that hosts unblock first so exempt names resolve for iptables."""
        assert cmd.cmd_total_block_refresh([]) == 0
        assert steps == ["hosts", "flush", "ipt"]

    def test_requires_root(self, steps: list[str]) -> None:
        """Test that non-root exits 1 and touches nothing."""
        with patch(f"{PKG}.os.geteuid", return_value=1000):
            assert cmd.cmd_total_block_refresh([]) == 1
        assert steps == []

    def test_no_active_block_is_noop(self, steps: list[str]) -> None:
        """Test that without a lock there is nothing to reconcile."""
        with patch(f"{PKG}.is_total_block_active", return_value=False):
            assert cmd.cmd_total_block_refresh([]) == 0
        assert steps == []

    def test_unknown_args_rejected(self, steps: list[str]) -> None:
        """Test that stray arguments are an error."""
        assert cmd.cmd_total_block_refresh(["--now"]) == 2
        assert steps == []

    def test_hosts_failure_stops_before_iptables(self, steps: list[str]) -> None:
        """Test that a failed hosts step never reaches the firewall."""
        with patch(f"{PKG}.refresh_total_block_hosts", return_value=False):
            assert cmd.cmd_total_block_refresh([]) == 1
        assert steps == []

    def test_iptables_failure_exits_nonzero(self, steps: list[str]) -> None:
        """Test that an iptables failure is reported."""
        with patch(f"{PKG}.refresh_total_block_iptables", return_value=False):
            assert cmd.cmd_total_block_refresh([]) == 1
        assert steps == ["hosts", "flush"]


class TestRegistration:
    """The command is reachable during the lock it reconciles."""

    def test_lock_exempt_and_unconfigured_ok(self) -> None:
        """Test that neither lock, nor a missing API key, refuses it."""
        assert NAME in _TOTAL_BLOCK_EXEMPT_COMMANDS
        assert NAME in _MANUAL_LOCK_EXEMPT_COMMANDS
        assert NAME in UNCONFIGURED_OK

    def test_has_help_text(self) -> None:
        """Test that help lists it."""
        assert NAME in ALL_COMMAND_DESCRIPTIONS
