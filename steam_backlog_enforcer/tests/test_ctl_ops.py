"""Tests for the allowlisted ops in ``_ctl_ops``.

Every privileged collaborator (journalctl, the store window, the total block,
the playtime mounts) is mocked; state-file ownership is checked against
tmp_path files and a mocked ``os.chown``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_ops, _fast_install_progress
from steam_backlog_enforcer._ctl_ops import _hand_back_state_file
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx

if TYPE_CHECKING:
    from pathlib import Path


class TestSimpleOps:
    """ping and status."""

    def test_ping(self) -> None:
        """ping answers pong."""
        assert _ctl_ops.op_ping(make_ctx(), {}) == {"pong": True}

    def test_status_running(self) -> None:
        """status reports running state, start time, restart time and pid."""
        with patch.object(_ctl_ops, "restart_available_at", return_value=None):
            data = _ctl_ops.op_status(make_ctx(), {})
        assert data["state"] == "running"
        assert data["started_at"] == "2026-01-01T00:00:00+00:00"
        assert data["restart_available_at"] is None
        assert isinstance(data["pid"], int)

    def test_status_reports_fast_installs(self, tmp_path: Path) -> None:
        """status lists a tracked fast install with its phase."""
        log = tmp_path / "log"
        log.write_bytes(b"Shutting down the Steam client...\r\n")
        _fast_install_progress.track(7, "G", log, offset=0, now=0.0)
        _fast_install_progress.poll_trackers({7})
        with patch.object(_ctl_ops, "restart_available_at", return_value=None):
            data = _ctl_ops.op_status(make_ctx(), {})
        runs = data["fast_installs"]
        assert isinstance(runs, list)
        (run,) = runs
        assert run["name"] == "G"
        assert run["phase"] == "shutting Steam down"
        assert run["percent"] is None

    def test_status_without_fast_installs(self) -> None:
        """status sends an empty fast-install list when none run."""
        with patch.object(_ctl_ops, "restart_available_at", return_value=None):
            assert _ctl_ops.op_status(make_ctx(), {})["fast_installs"] == []

    def test_status_restarting(self) -> None:
        """A set restart event makes status report restarting."""
        ctx = make_ctx()
        ctx.restart_event.set()
        assert _ctl_ops.op_status(ctx, {})["state"] == "restarting"


class TestJournalTail:
    """journal_tail shells out to journalctl with a capped line count."""

    def _run(self, **kwargs: object) -> MagicMock:
        return MagicMock(**kwargs)

    def test_default_lines_and_truncation(self) -> None:
        """journal_tail defaults to 50 lines and truncates long ones to 500 chars."""
        out = "a\n" + "x" * 900 + "\n"
        with patch.object(
            _ctl_ops.subprocess, "run", return_value=self._run(stdout=out)
        ) as run:
            data = _ctl_ops.op_journal_tail(make_ctx(), {})
        assert data["lines"] == ["a", "x" * 500]
        argv = run.call_args.args[0]
        assert argv[argv.index("-n") + 1] == "50"

    def test_explicit_lines(self) -> None:
        """journal_tail passes an explicit line count to journalctl."""
        with patch.object(
            _ctl_ops.subprocess, "run", return_value=self._run(stdout="")
        ) as run:
            _ctl_ops.op_journal_tail(make_ctx(), {"lines": 7})
        assert "7" in run.call_args.args[0]

    def test_lines_out_of_range(self) -> None:
        """A line count above the cap is rejected."""
        with pytest.raises(CtlError):
            _ctl_ops.op_journal_tail(make_ctx(), {"lines": 201})

    @pytest.mark.parametrize(
        "exc", [OSError("gone"), subprocess.TimeoutExpired("journalctl", 5)]
    )
    def test_failure_is_op_failed(self, exc: Exception) -> None:
        """journalctl failing or timing out becomes op_failed."""
        with (
            patch.object(_ctl_ops.subprocess, "run", side_effect=exc),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_ops.op_journal_tail(make_ctx(), {})
        assert caught.value.code == "op_failed"


class TestHandBackStateFile:
    """A state.json root just created is chowned to the config dir's owner."""

    def test_chowns_when_owner_differs(self, tmp_path: Path) -> None:
        """state.json is chowned to the config dir owner when they differ."""
        state = tmp_path / "state.json"
        state.write_text("{}")
        owner = MagicMock(st_uid=4242, st_gid=4343)
        with (
            patch.object(_ctl_ops, "CONFIG_DIR", MagicMock(stat=lambda: owner)),
            patch.object(_ctl_ops, "STATE_FILE", state),
            patch.object(_ctl_ops.os, "chown") as chown,
        ):
            _hand_back_state_file()
        chown.assert_called_once_with(state, 4242, 4343)

    def test_leaves_matching_owner_alone(self, tmp_path: Path) -> None:
        """No chown happens when the owner already matches."""
        state = tmp_path / "state.json"
        state.write_text("{}")
        with (
            patch.object(_ctl_ops, "CONFIG_DIR", tmp_path),
            patch.object(_ctl_ops, "STATE_FILE", state),
            patch.object(_ctl_ops.os, "chown") as chown,
        ):
            _hand_back_state_file()
        chown.assert_not_called()

    def test_missing_file_is_tolerated(self, tmp_path: Path) -> None:
        """A missing state.json does not raise."""
        with (
            patch.object(_ctl_ops, "CONFIG_DIR", tmp_path),
            patch.object(_ctl_ops, "STATE_FILE", tmp_path / "absent.json"),
        ):
            _hand_back_state_file()
