"""Per-run logging.

Everything a run does lands in one file the user can copy-paste verbatim when
something goes wrong. The first version of this tool had no logging at all, and
when a run failed the evidence was gone: Steam owns appmanifest_<appid>.acf and
had already overwritten the manifest we wrote by the time anyone looked. So the
log records the manifest *verbatim, before and after* every write, alongside the
full output of every subprocess.

Subprocess output is teed through a pty rather than captured with
`capture_output=True`. depotdownloader prompts for a password (and possibly a
Steam Guard code) on stdin; prompt text written to a captured/buffered pipe never
reaches the terminal, so the process looks hung with no visible request for
input. A pty keeps it in line-buffered interactive mode and lets us
mirror every byte to both the terminal and the log.
"""

from __future__ import annotations

import errno
import io
import logging
import os
import pty
import select
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

LOG_DIR = Path.home() / ".local/state/steam-game-installer"
LOGGER_NAME = "steam_installer"

_CONSOLE_FORMAT = "%(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Read granularity for the pty relay. Large enough that depotdownloader's
# progress spam doesn't cost a syscall per line, small enough to stay responsive.
_READ_CHUNK = 65536


@dataclass
class RunLog:
    """A single run's log file, plus the `latest.log` symlink pointing at it."""

    path: Path
    logger: logging.Logger

    def section(self, title: str) -> None:
        """A visual divider so a pasted log is skimmable."""
        self.logger.debug("=" * 72)
        self.logger.debug(title)
        self.logger.debug("=" * 72)

    def file_contents(self, label: str, path: Path) -> None:
        """Record a file verbatim. Used for manifests before/after every write."""
        self.section(f"{label}: {path}")
        try:
            self.logger.debug("\n%s", path.read_text())
        except OSError as exc:
            self.logger.debug("(unreadable: %s)", exc)


def setup(appid: int | None, verbose: bool = False) -> RunLog:
    """Start a run log. Console stays terse; the file gets everything at DEBUG."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = LOG_DIR / f"run-{stamp}-{appid if appid is not None else 'noappid'}.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # A second setup() in the same process (tests) must not double-log.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    logger.addHandler(console)

    _point_latest_at(path)
    return RunLog(path=path, logger=logger)


def _point_latest_at(path: Path) -> None:
    """Best-effort `latest.log` symlink -- a stale symlink must never fail a run."""
    latest = LOG_DIR / "latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(path.name)
    except OSError:
        pass


def run_logged(
    cmd: list[str],
    logger: logging.Logger,
    timeout: float | None = None,
) -> tuple[int, str]:
    """Run `cmd` on a pty, mirroring output to both the terminal and the log.

    Returns (returncode, combined_output). stdin stays attached to the real
    terminal so interactive prompts (depotdownloader's password / Steam Guard) work
    exactly as they do without logging.
    """
    logger.debug("$ %s", shlex.join(cmd))
    started = time.monotonic()

    master_fd, slave_fd = pty.openpty()
    chunks: list[bytes] = []
    try:
        process = subprocess.Popen(
            cmd,
            stdout=slave_fd,
            stderr=slave_fd,
            stdin=_stdin_for_child(slave_fd),
            close_fds=True,
        )
    except OSError:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    # The child owns the slave end now; holding it open here would keep the
    # master readable forever and hang the relay after the child exits.
    os.close(slave_fd)

    try:
        _relay(master_fd, chunks, process, timeout, started)
    except subprocess.TimeoutExpired as exc:
        # Record what the child managed to say before it hung, then re-raise.
        # Losing it here defeats the whole point of the log in precisely the
        # case where it matters most -- a download hung until its timeout.
        output = _log_output(logger, chunks, started, returncode=None)
        process.wait()
        exc.output = output.encode()
        raise
    finally:
        os.close(master_fd)

    returncode = process.wait()
    output = _log_output(logger, chunks, started, returncode)
    return returncode, output


def _log_output(
    logger: logging.Logger,
    chunks: list[bytes],
    started: float,
    returncode: int | None,
) -> str:
    output = b"".join(chunks).decode("utf-8", errors="replace")
    elapsed = time.monotonic() - started
    logger.debug("--- output (%d bytes) ---\n%s", len(output), output)
    if returncode is None:
        logger.debug("TIMED OUT after %.1fs", elapsed)
    else:
        logger.debug("exit=%d elapsed=%.1fs", returncode, elapsed)
    return output


def _read_pty(fd: int, size: int) -> bytes:
    """Indirection so tests can fault-inject the pty read without patching the
    global `os.read`, which subprocess itself uses during spawn."""
    return os.read(fd, size)


def _stdin_for_child(slave_fd: int) -> int:
    """The child's stdin: the real terminal when there is one, else the pty.

    depotdownloader needs a readable stdin to prompt for a password, but `sys.stdin`
    is not always a real file descriptor -- under pytest's capture, systemd, or
    a piped invocation it has no fileno(). Falling back to the pty's slave end
    keeps the child on a terminal-like stdin instead of crashing.
    """
    try:
        return sys.stdin.fileno()
    except (AttributeError, ValueError, OSError, io.UnsupportedOperation):
        return slave_fd


def _relay(
    master_fd: int,
    chunks: list[bytes],
    process: subprocess.Popen,
    timeout: float | None,
    started: float,
) -> None:
    """Pump pty output to stdout and `chunks` until the child closes it."""
    while True:
        if timeout is not None and time.monotonic() - started > timeout:
            process.kill()
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            ready, _, _ = select.select([master_fd], [], [], 0.2)
        except OSError:
            break
        if not ready:
            # No output pending; the child may still have exited.
            if process.poll() is not None:
                break
            continue
        try:
            data = _read_pty(master_fd, _READ_CHUNK)
        except OSError as exc:
            # EIO is the normal "child closed the pty" signal on Linux.
            if exc.errno == errno.EIO:
                break
            raise
        if not data:
            break
        chunks.append(data)
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
