"""Tests for _serve_guard's staleness check and process termination.

The other half of the guard's tests lives in test_serve_guard.py; this file was
split off to stay inside the 250-line cap.

``os.kill`` is mocked in every termination test, and the one test that passes a
real pid passes this process's own — which the guard is required to refuse.
No test here can signal anything.
"""

from __future__ import annotations

import errno
import os
import signal
import socket
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _serve_guard
from steam_backlog_enforcer.tests._fake_proc import add_pid, make_proc, patch_proc

if TYPE_CHECKING:
    from pathlib import Path

_HOST = "127.0.0.1"


class TestProcessStartedAt:
    """Tests for reading a process start time."""

    def test_returns_directory_mtime(self, tmp_path: Path) -> None:
        proc = make_proc(tmp_path)
        pid_dir = add_pid(proc, 100)
        os.utime(pid_dir, (1000.0, 1000.0))
        with patch_proc(proc):
            assert _serve_guard.process_started_at(100) == 1000.0

    def test_missing_process_returns_none(self, tmp_path: Path) -> None:
        proc = make_proc(tmp_path)
        with patch_proc(proc):
            assert _serve_guard.process_started_at(4321) is None


class TestNewestPySince:
    """Tests for deciding whether a running server loaded outdated code."""

    def test_no_newer_file_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        os.utime(tmp_path / "a.py", (1000.0, 1000.0))
        with patch.object(_serve_guard, "_PACKAGE_ROOT", tmp_path):
            assert _serve_guard.newest_py_since(2000.0) is None

    def test_newer_file_is_named(self, tmp_path: Path) -> None:
        # The path is returned rather than a bool so the restart message can
        # name the file: killing a server is always auditable.
        nested = tmp_path / "pkg"
        nested.mkdir()
        (nested / "b.py").write_text("x", encoding="utf-8")
        os.utime(nested / "b.py", (3000.0, 3000.0))
        with patch.object(_serve_guard, "_PACKAGE_ROOT", tmp_path):
            assert _serve_guard.newest_py_since(2000.0) == nested / "b.py"

    def test_the_newest_of_several_wins(self, tmp_path: Path) -> None:
        for name, mtime in (("a.py", 3000.0), ("b.py", 4000.0), ("c.py", 3500.0)):
            (tmp_path / name).write_text("x", encoding="utf-8")
            os.utime(tmp_path / name, (mtime, mtime))
        with patch.object(_serve_guard, "_PACKAGE_ROOT", tmp_path):
            assert _serve_guard.newest_py_since(2000.0) == tmp_path / "b.py"

    def test_vanished_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "gone.py").symlink_to(tmp_path / "missing.py")
        with patch.object(_serve_guard, "_PACKAGE_ROOT", tmp_path):
            assert _serve_guard.newest_py_since(1000.0) is None


class TestReadPpid:
    """Tests for parsing the parent pid out of /proc/<pid>/stat."""

    def test_reads_ppid_past_a_comm_with_spaces(self, tmp_path: Path) -> None:
        proc = make_proc(tmp_path)
        add_pid(proc, 100, ppid=42)
        with patch_proc(proc):
            assert _serve_guard._read_ppid(100) == 42

    def test_missing_stat_returns_none(self, tmp_path: Path) -> None:
        proc = make_proc(tmp_path)
        add_pid(proc, 100)
        with patch_proc(proc):
            assert _serve_guard._read_ppid(100) is None

    def test_truncated_stat_returns_none(self, tmp_path: Path) -> None:
        proc = make_proc(tmp_path)
        add_pid(proc, 100)
        (proc / "100" / "stat").write_text("100 (py) S", encoding="utf-8")
        with patch_proc(proc):
            assert _serve_guard._read_ppid(100) is None

    def test_non_numeric_ppid_returns_none(self, tmp_path: Path) -> None:
        proc = make_proc(tmp_path)
        add_pid(proc, 100)
        (proc / "100" / "stat").write_text("100 (py) S bogus 1", encoding="utf-8")
        with patch_proc(proc):
            assert _serve_guard._read_ppid(100) is None


class TestOwnPidChain:
    """Tests for the self-protection ancestry walk."""

    def test_includes_self_and_ancestors(self) -> None:
        with patch.object(_serve_guard, "_read_ppid", side_effect=[7, None]):
            chain = _serve_guard._own_pid_chain()
        assert os.getpid() in chain
        assert 7 in chain

    def test_stops_at_pid_zero(self) -> None:
        # init's parent is 0, which is not a process and must not be walked.
        with patch.object(_serve_guard, "_read_ppid", return_value=0):
            chain = _serve_guard._own_pid_chain()
        assert chain == {os.getpid()}

    def test_a_cycle_terminates(self) -> None:
        # A stat file claiming a process is its own parent must not hang the
        # walk; the guard runs before the server starts, so a spin is a freeze.
        with patch.object(_serve_guard, "_read_ppid", return_value=os.getpid()):
            assert _serve_guard._own_pid_chain() == {os.getpid()}


class TestPortIsFree:
    """Tests for the real bind probe."""

    def test_unused_port_is_free(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((_HOST, 0))
            port = probe.getsockname()[1]
        assert _serve_guard.port_is_free(_HOST, port) is True

    def test_bound_port_is_not_free(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind((_HOST, 0))
            held.listen(1)
            port = held.getsockname()[1]
            assert _serve_guard.port_is_free(_HOST, port) is False


class TestTerminate:
    """Tests for stopping a stale server.

    ``_serve_guard.os`` is replaced wholesale in every test, so no signal can
    reach a real process even if the guard's own protections were removed.
    """

    def test_refuses_to_signal_self(self) -> None:
        # The process running this check matches is_our_server by construction,
        # so a wrong owner lookup would otherwise have it kill itself.
        with (
            patch.object(_serve_guard, "os") as fake_os,
            patch.object(_serve_guard, "_read_ppid", return_value=None),
        ):
            fake_os.getpid.return_value = os.getpid()
            assert _serve_guard.terminate(os.getpid(), _HOST, 8000) is False
        fake_os.kill.assert_not_called()

    def test_sigterm_frees_the_port(self) -> None:
        with (
            patch.object(_serve_guard, "_own_pid_chain", return_value=set()),
            patch.object(_serve_guard, "_TERM_WAIT_SECONDS", 0.05),
            patch.object(_serve_guard, "_POLL_INTERVAL", 0.0),
            patch.object(_serve_guard, "port_is_free", return_value=True),
            patch.object(_serve_guard, "os") as fake_os,
        ):
            assert _serve_guard.terminate(999, _HOST, 8000) is True
        fake_os.kill.assert_called_once_with(999, signal.SIGTERM)

    def test_escalates_to_sigkill(self) -> None:
        # The port frees only once SIGKILL lands, driven off the recorded
        # signals rather than a call count, so the SIGTERM window's length
        # cannot make this flaky.
        sent: list[int] = []

        def freed(_host: str, _port: int) -> bool:
            return signal.SIGKILL in sent

        with (
            patch.object(_serve_guard, "_own_pid_chain", return_value=set()),
            patch.object(_serve_guard, "_TERM_WAIT_SECONDS", 0.01),
            patch.object(_serve_guard, "_POLL_INTERVAL", 0.0),
            patch.object(_serve_guard, "port_is_free", side_effect=freed),
            patch.object(_serve_guard, "os") as fake_os,
        ):
            fake_os.kill.side_effect = lambda _pid, sig: sent.append(sig)
            assert _serve_guard.terminate(999, _HOST, 8000) is True
        assert sent == [signal.SIGTERM, signal.SIGKILL]

    def test_gives_up_when_the_port_never_frees(self) -> None:
        with (
            patch.object(_serve_guard, "_own_pid_chain", return_value=set()),
            patch.object(_serve_guard, "_TERM_WAIT_SECONDS", 0.0),
            patch.object(_serve_guard, "_POLL_INTERVAL", 0.0),
            patch.object(_serve_guard, "port_is_free", return_value=False),
            patch.object(_serve_guard, "os"),
        ):
            assert _serve_guard.terminate(999, _HOST, 8000) is False

    def test_already_exited_process_is_not_an_error(self) -> None:
        with (
            patch.object(_serve_guard, "_own_pid_chain", return_value=set()),
            patch.object(_serve_guard, "_TERM_WAIT_SECONDS", 0.0),
            patch.object(_serve_guard, "_POLL_INTERVAL", 0.0),
            patch.object(_serve_guard, "port_is_free", return_value=True),
            patch.object(_serve_guard, "os") as fake_os,
        ):
            fake_os.kill.side_effect = ProcessLookupError
            assert _serve_guard.terminate(999, _HOST, 8000) is True

    def test_permission_denied_is_not_an_error(self) -> None:
        with (
            patch.object(_serve_guard, "_own_pid_chain", return_value=set()),
            patch.object(_serve_guard, "_TERM_WAIT_SECONDS", 0.0),
            patch.object(_serve_guard, "_POLL_INTERVAL", 0.0),
            patch.object(_serve_guard, "port_is_free", return_value=False),
            patch.object(_serve_guard, "os") as fake_os,
        ):
            fake_os.kill.side_effect = PermissionError(errno.EPERM, "not yours")
            assert _serve_guard.terminate(999, _HOST, 8000) is False
