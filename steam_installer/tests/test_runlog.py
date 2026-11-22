"""Tests for runlog."""

from __future__ import annotations

import errno
from pathlib import Path
import subprocess
import sys
from typing import Never

import pytest

from steam_installer import runlog
from steam_installer.runlog import _point_latest_at, _read_pty

pytestmark = pytest.mark.usefixtures("cli_logs")


def test_setup_creates_log_file_and_latest_symlink() -> None:
    """Setup creates log file and latest symlink."""
    log = runlog.setup(1771300)

    assert log.path.is_file()
    assert "1771300" in log.path.name
    latest = runlog.LOG_DIR / "latest.log"
    assert latest.is_symlink()
    assert latest.resolve() == log.path.resolve()


def test_setup_without_appid_still_names_the_file() -> None:
    """Setup without appid still names the file."""
    log = runlog.setup(None)
    assert "noappid" in log.path.name


def test_setup_twice_does_not_duplicate_handlers() -> None:
    """A second setup() in one process must not write every line twice."""
    runlog.setup(1)
    log = runlog.setup(2)
    log.logger.info("once")
    assert log.path.read_text(encoding="utf-8").count("once") == 1


def test_run_logged_records_command_output_and_exit_code(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Run logged records command output and exit code."""
    log = runlog.setup(1771300)

    returncode, output = runlog.run_logged(
        ["bash", "-c", "echo to-stdout; echo to-stderr >&2; exit 7"], log.logger
    )

    assert returncode == 7
    assert "to-stdout" in output
    assert "to-stderr" in output

    # Mirrored to the terminal...
    assert "to-stdout" in capfd.readouterr().out
    # ...and recorded in the log, along with the argv and exit code.
    contents = log.path.read_text(encoding="utf-8")
    assert "to-stdout" in contents
    assert "echo to-stdout" in contents
    assert "exit=7" in contents


def test_run_logged_child_sees_a_tty() -> None:
    """The whole reason for the pty: steamcmd only prompts interactively for a
    password when it believes it is attached to a terminal. A plain pipe makes
    the prompt invisible and the run looks hung.
    """
    log = runlog.setup(1771300)
    _, output = runlog.run_logged(
        [sys.executable, "-c", "import sys; print(sys.stdout.isatty())"], log.logger
    )
    assert "True" in output


def test_run_logged_times_out() -> None:
    """Run logged times out."""
    log = runlog.setup(1771300)
    with pytest.raises(subprocess.TimeoutExpired):
        runlog.run_logged(["sleep", "10"], log.logger, timeout=0.5)


def test_file_contents_records_manifest_verbatim(tmp_path: Path) -> None:
    """File contents records manifest verbatim."""
    log = runlog.setup(1771300)
    manifest = tmp_path / "appmanifest_1771300.acf"
    manifest.write_text('"AppState"\n{\n\t"StateFlags"\t\t"4"\n}\n')

    log.file_contents("Manifest before run", manifest)

    contents = log.path.read_text(encoding="utf-8")
    assert "Manifest before run" in contents
    assert '"StateFlags"' in contents


def test_file_contents_survives_missing_file(tmp_path: Path) -> None:
    """A first-ever install has no manifest yet; that must not kill the run."""
    log = runlog.setup(1771300)
    log.file_contents("Manifest before run", tmp_path / "absent.acf")
    assert "unreadable" in log.path.read_text(encoding="utf-8")


def test_run_logged_records_output_even_on_timeout() -> None:
    """A steamcmd hang at the 3600s timeout is exactly when the log matters
    most; discarding what the child said before hanging defeats the point."""
    log = runlog.setup(1771300)
    marker = "TIMEOUT" + "MARKER"
    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        runlog.run_logged(
            ["bash", "-c", f'printf "%s\\n" "{marker}"; sleep 30'],
            log.logger,
            timeout=1.0,
        )

    contents = log.path.read_text(encoding="utf-8")
    assert "--- output" in contents
    assert marker in contents
    assert "TIMED OUT" in contents
    assert marker.encode() in excinfo.value.output


def test_point_latest_at_survives_a_broken_log_dir() -> None:
    """A stale or unwritable latest.log must never fail an otherwise fine run."""
    log = runlog.setup(1)
    latest = runlog.LOG_DIR / "latest.log"
    latest.unlink()
    latest.mkdir()  # a directory where the symlink should go

    _point_latest_at(log.path)  # must not raise

    assert latest.is_dir()


def test_run_logged_closes_pty_fds_when_spawn_fails() -> None:
    """A leaked master/slave pair per failed spawn would exhaust the fd table."""
    log = runlog.setup(1)
    before = len(list(Path("/proc/self/fd").iterdir()))

    with pytest.raises(FileNotFoundError):
        runlog.run_logged(["definitely-not-a-real-binary-xyz"], log.logger)

    assert len(list(Path("/proc/self/fd").iterdir())) == before


def test_run_logged_stops_when_select_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A closed master fd surfaces as OSError from select; end the relay."""
    log = runlog.setup(1)
    monkeypatch.setattr(
        runlog.select, "select", lambda *a, **kw: (_ for _ in ()).throw(OSError)
    )

    returncode, output = runlog.run_logged(["true"], log.logger)

    assert returncode == 0
    assert output == ""


def test_run_logged_reraises_unexpected_read_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EIO means "child closed the pty" and ends the loop; anything else is a
    real failure and must not be swallowed."""
    log = runlog.setup(1)
    # Force select to always report readable so os.read is definitely reached.
    monkeypatch.setattr(runlog.select, "select", lambda *a, **kw: ([a[0][0]], [], []))

    def bad_read(fd: int, size: int) -> Never:
        raise OSError(errno.EBADF, "bad file descriptor")

    monkeypatch.setattr(runlog, "_read_pty", bad_read)

    with pytest.raises(OSError, match="bad file descriptor") as excinfo:
        runlog.run_logged(["bash", "-c", "echo hi; sleep 0.2"], log.logger)
    assert excinfo.value.errno == errno.EBADF


def test_run_logged_exits_when_child_dies_without_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """select never reports readable, so the loop must notice via poll() that
    the child is gone rather than spinning forever."""
    log = runlog.setup(1)
    monkeypatch.setattr(runlog.select, "select", lambda *a, **kw: ([], [], []))

    returncode, output = runlog.run_logged(["true"], log.logger)

    assert returncode == 0
    assert output == ""


def test_run_logged_handles_empty_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero-byte read is EOF on the pty."""
    log = runlog.setup(1)
    real_read = _read_pty
    calls = {"n": 0}

    def once_then_eof(fd: int, size: int) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            return real_read(fd, size)
        return b""

    monkeypatch.setattr(runlog, "_read_pty", once_then_eof)

    returncode, _ = runlog.run_logged(["bash", "-c", "echo hi"], log.logger)
    assert returncode == 0


def test_run_logged_survives_a_child_that_writes_nothing() -> None:
    """Exercises the poll()-based exit when the pty never becomes readable."""
    log = runlog.setup(1)
    returncode, output = runlog.run_logged(["true"], log.logger)
    assert returncode == 0
    assert output == ""
