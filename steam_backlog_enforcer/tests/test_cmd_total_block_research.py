"""The `total-block-research` command: root-only, to the lock end, lock-exempt."""

from __future__ import annotations

from datetime import UTC, datetime
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _cmd_total_block_research as cmd
from steam_backlog_enforcer import _research_window as window
from steam_backlog_enforcer._command_gate import UNCONFIGURED_OK
from steam_backlog_enforcer._command_help import ALL_COMMAND_DESCRIPTIONS
from steam_backlog_enforcer._command_locks import (
    _MANUAL_LOCK_EXEMPT_COMMANDS,
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import _dispatch_extra_command
from steam_backlog_enforcer.tests._research_helpers import HOUR, LOCK_END, NOW, lock

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steam_backlog_enforcer.tests._total_block_paths import Paths

PKG = "steam_backlog_enforcer._cmd_total_block_research"
NAME = "total-block-research"
UNTIL = datetime.fromtimestamp(NOW + 5 * HOUR, tz=UTC).isoformat()


@pytest.fixture(autouse=True)
def _root_with_lock(total_block_paths: Paths) -> Iterator[None]:
    """Every test runs as root inside an active total block, clock at NOW."""
    lock(total_block_paths)
    with (
        patch(f"{PKG}.os.geteuid", return_value=0),
        patch("steam_backlog_enforcer._research_window.now", return_value=NOW),
    ):
        yield


class TestCommand:
    """Argument handling and the refusals."""

    def test_opens_the_window(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that a valid expiry records the window and exits 0."""
        assert cmd.cmd_total_block_research(["--until", UNTIL]) == 0
        record = window.read_record()
        assert record is not None
        assert record.until == NOW + 5 * HOUR
        assert "Librarian" in capsys.readouterr().out

    def test_equals_form(self) -> None:
        """Test that --until=VALUE works too."""
        assert cmd.cmd_total_block_research([f"--until={UNTIL}"]) == 0

    @pytest.mark.parametrize(
        "args",
        [[], ["--until"], ["--until", "x", "y"], ["--soon"], ["--until", "nope"]],
    )
    def test_bad_usage_is_2_and_writes_nothing(self, args: list[str]) -> None:
        """Test that malformed arguments are usage errors."""
        assert cmd.cmd_total_block_research(args) == 2
        assert window.read_record() is None

    def test_requires_root(self) -> None:
        """Test that non-root exits 1 before touching state."""
        with patch(f"{PKG}.os.geteuid", return_value=1000):
            assert cmd.cmd_total_block_research(["--until", UNTIL]) == 1
        assert window.read_record() is None

    def test_after_the_lock_end_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that the lock's end is the ceiling, with the reason printed."""
        late = datetime.fromtimestamp(LOCK_END + 1, tz=UTC).isoformat()
        assert cmd.cmd_total_block_research(["--until", late]) == 1
        assert "end of the total block" in capsys.readouterr().out
        assert window.read_record() is None

    def test_second_run_extends_once(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that a later expiry extends the open window, one time only."""
        assert cmd.cmd_total_block_research(["--until", UNTIL]) == 0
        first = window.read_record()
        assert first is not None
        assert "extendable once" in capsys.readouterr().out
        later = datetime.fromtimestamp(NOW + 30 * HOUR, tz=UTC).isoformat()
        assert cmd.cmd_total_block_research(["--until", later]) == 0
        out = capsys.readouterr().out
        assert "extended until" in out
        assert "extendable once" not in out
        assert "the one extension" in out
        record = window.read_record()
        assert record is not None
        assert (record.opened_at, record.until) == (first.opened_at, first.until)
        assert record.extended_until == NOW + 30 * HOUR
        again = datetime.fromtimestamp(NOW + 31 * HOUR, tz=UTC).isoformat()
        assert cmd.cmd_total_block_research(["--until", again]) == 1
        assert window.read_record() == record

    def test_earlier_expiry_never_shortens(self) -> None:
        """Test that a rerun with an earlier time leaves the window alone."""
        assert cmd.cmd_total_block_research(["--until", UNTIL]) == 0
        first = window.read_record()
        sooner = datetime.fromtimestamp(NOW + HOUR, tz=UTC).isoformat()
        assert cmd.cmd_total_block_research(["--until", sooner]) == 1
        assert window.read_record() == first

    def test_no_active_block_is_refused(self, total_block_paths: Paths) -> None:
        """Test that without a lock the command exits 1."""
        total_block_paths.lock_file.unlink()
        assert cmd.cmd_total_block_research(["--until", UNTIL]) == 1


class TestRegistration:
    """Reachable during the lock it loosens, and nowhere else."""

    def test_lock_exempt(self) -> None:
        """Test that the total block lets it through (and the nested manual set)."""
        assert NAME in _TOTAL_BLOCK_EXEMPT_COMMANDS
        assert _TOTAL_BLOCK_EXEMPT_COMMANDS <= _MANUAL_LOCK_EXEMPT_COMMANDS

    def test_needs_a_configured_install(self) -> None:
        """Test that a missing API key is a loud failure, not a silent pass."""
        assert NAME not in UNCONFIGURED_OK

    def test_has_help_text(self) -> None:
        """Test that help lists it."""
        assert NAME in ALL_COMMAND_DESCRIPTIONS

    def test_dispatch_hands_over_the_argv_tail_and_exits(self) -> None:
        """Test that main dispatch passes the tail and exits with its code."""
        argv = ["prog", NAME, "--until", UNTIL]
        with (
            patch.object(sys, "argv", argv),
            patch("steam_backlog_enforcer.main.cmd_total_block_research") as handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            handler.return_value = 7
            _dispatch_extra_command(NAME, Config(), State())
        assert exc_info.value.code == 7
        handler.assert_called_once_with(["--until", UNTIL])
