"""Installing games through steam-game-installer, for download speed.

depotdownloader saturates the link far better than the Steam client, and
steam-game-installer (``~/src/steam-game-installer``) wraps it so Steam accepts
the result as a real install. It also adopts whatever Steam already staged, so
taking over a slow client download loses nothing.

Two modes, picked by whether anyone can answer a prompt:

* **Foreground** (stdin is a terminal - ``pick-manual``, ``done``...): run with
  the terminal attached, so depotdownloader's progress shows and a password /
  Steam Guard prompt can be answered.
* **Detached** (no terminal): spawn in its own session. The root daemon returns
  at once; :func:`poll_fast_installs` reaps the run on later passes, records a
  failure (the caller falls back to ``steam://install``) and interrupts a run
  whose output stalled - likely a login prompt nobody will answer, with Steam
  shut down. A web job loops that reaper until the run ends. Either way the
  log is followed for progress (:mod:`_fast_install_progress`).

The installer closes Steam, so it is refused while a game is running. Another
app mid-download is no reason to wait: asked to leave with ``steam -shutdown``,
Steam resumes the transfer when it comes back.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer import _fast_install_progress as _fip
from steam_backlog_enforcer import config as _config
from steam_backlog_enforcer._desktop_env import resolve_desktop_user
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._fast_install_cmd import build_cmd, installer_path
from steam_backlog_enforcer._fast_install_failure import failure_reason
from steam_backlog_enforcer._steam_restart_guard import game_is_running
from steam_backlog_enforcer._steam_state import is_game_fully_installed

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

_INSTALLER_LOG = "~/.local/state/steam-game-installer/latest.log"
# depotdownloader prints a line per finished chunk, so a healthy download is
# never silent this long; a login prompt waiting on /dev/null is.
STALL_SECONDS = 15 * 60
# How often a waiting (non-daemon) caller reaps its run.
_WAIT_POLL_SECONDS = 5


@dataclass
class _DetachedRun:
    """A daemon-spawned installer run, kept so it can be reaped."""

    app_id: int
    proc: subprocess.Popen[bytes]
    log_path: Path


_RUNS: list[_DetachedRun] = []
# Apps whose installer run failed in this process, with the reason. They go
# straight to the steam:// fallback from then on, so a broken login cannot
# close Steam on every 3-second pass.
_FAILED: dict[int, str] = {}


def _refusal() -> str | None:
    """Why closing Steam right now would do damage, or None if it is safe."""
    if game_is_running():
        return "a game is running and closing Steam would kill it"
    return None


def is_fast_installing(app_id: int) -> bool:
    """Whether this process has a live detached installer run for *app_id*."""
    return any(run.app_id == app_id for run in _RUNS)


def fast_install_failure(app_id: int) -> str | None:
    """Why this process's installer run for *app_id* failed, if it did."""
    return _FAILED.get(app_id)


def _stalled(run: _DetachedRun) -> bool:
    """Whether a live run has printed nothing for :data:`STALL_SECONDS`."""
    try:
        return time.time() - run.log_path.stat().st_mtime > STALL_SECONDS
    except OSError:
        return False


def poll_fast_installs() -> None:
    """Reap finished detached runs and interrupt stalled ones.

    SIGINT, not SIGTERM: the installer turns it into KeyboardInterrupt, and its
    ``finally`` restarts the Steam client it shut down. SIGTERM would leave
    Steam closed.
    """
    for run in list(_RUNS):
        returncode = run.proc.poll()
        if returncode is None:
            if _stalled(run):
                logger.warning(
                    "steam-game-installer for AppID=%d silent for %ds — "
                    "interrupting (see %s).",
                    run.app_id,
                    STALL_SECONDS,
                    run.log_path,
                )
                os.killpg(run.proc.pid, signal.SIGINT)
            continue
        _RUNS.remove(run)
        if returncode == 0:
            logger.info("steam-game-installer finished AppID=%d.", run.app_id)
            continue
        _FAILED[run.app_id] = failure_reason(run.log_path, returncode)
        _fip.mark_failed(run.app_id, _FAILED[run.app_id])
        logger.warning(
            "steam-game-installer failed for AppID=%d: %s. Falling back to "
            "Steam's own download. Log: %s",
            run.app_id,
            _FAILED[run.app_id],
            run.log_path,
        )
    _fip.poll_trackers({run.app_id for run in _RUNS}, is_game_fully_installed)


def _spawn_detached(cmd: list[str], app_id: int, label: str = "") -> None:
    """Start the installer in its own session, output to a log file."""
    # Per user: the daemon's log is root-owned, and a web job runs as the
    # desktop user - sharing one file made every job spawn raise.
    log_path = _config.CONFIG_DIR / f"fast_install-{os.geteuid()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The unit is KillMode=control-group: restarting the daemon would SIGTERM
    # an installer left in its cgroup, skipping the `finally` that restarts
    # Steam. A transient scope moves it out; --scope execs in place, so the
    # Popen pid below is still the session leader killpg needs.
    if os.geteuid() == 0 and shutil.which("systemd-run"):
        cmd = ["systemd-run", "--scope", "--quiet", "--collect", *cmd]
    with log_path.open("ab") as log:
        # Append mode starts at the end: earlier runs' lines are never parsed.
        _fip.track(app_id, label, log_path, offset=log.tell(), now=time.monotonic())
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _RUNS.append(_DetachedRun(app_id, proc, log_path))
    logger.info("Started steam-game-installer for AppID=%d (log: %s)", app_id, log_path)


def _wait_detached(app_id: int, label: str) -> bool:
    """Reap this process's run for *app_id* until it ends; True on success."""
    reporter = _fip.WaitReporter(app_id, label, started=time.monotonic())
    while is_fast_installing(app_id):
        time.sleep(_WAIT_POLL_SECONDS)
        poll_fast_installs()
        reporter.report(time.monotonic())
    if app_id not in _FAILED:
        return True
    # "Failed" first: a job takes such a line as its verdict, so the run can
    # no longer end on a full progress bar and "Succeeded".
    _echo(
        f"Failed: fast install of {label}: {_FAILED[app_id]}. Steam's own "
        f"download takes over (log: {_INSTALLER_LOG})."
    )
    return False


def fast_install(
    app_id: int, label: str, prepare: Callable[[], object] = lambda: None
) -> bool:
    """Install *app_id* with steam-game-installer.

    *prepare* runs once the run is sure to start, before it does: the
    installer only finishes a manifest it finds, so this is where a fresh
    install gets one.

    Returns:
        True if the game was installed (foreground) or the run was started
        (detached); False if the caller should fall back to Steam's download.
    """
    if app_id in _FAILED:
        return False
    user = resolve_desktop_user()
    installer = installer_path(user)
    if installer is None:
        logger.warning("steam-game-installer not found; using Steam's download.")
        return False
    reason = _refusal()
    if reason is not None:
        _echo(f"  Fast install of {label} skipped: {reason}.")
        return False

    cmd = build_cmd(installer, app_id, user)
    prepare()
    if not sys.stdin.isatty():
        _spawn_detached(cmd, app_id, label)
        return os.geteuid() == 0 or _wait_detached(app_id, label)

    _echo(f"  Fast-installing {label} with steam-game-installer (Steam will close)...")
    returncode = subprocess.run(cmd, check=False).returncode
    if returncode == 0:
        return True
    _FAILED[app_id] = f"exit {returncode}"
    _echo(
        f"Failed: fast install of {label} (exit {returncode}, reasons above). "
        f"Steam's own download takes over (log: {_INSTALLER_LOG})."
    )
    return False
