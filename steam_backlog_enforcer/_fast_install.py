"""Installing games through steam-game-installer, for download speed.

depotdownloader saturates the link far better than the Steam client, and
steam-game-installer (``~/src/steam-game-installer``) wraps it so Steam accepts
the result as a real install. It also adopts whatever Steam already staged, so
taking over a slow client download loses nothing.

Two modes, picked by whether anyone can answer a prompt:

* **Foreground** (stdin is a terminal - ``pick-manual``, ``done``...): run to
  completion with the terminal attached, so depotdownloader's progress shows
  and a password / Steam Guard prompt can be answered.
* **Detached** (the daemon): spawn in its own session and return. Every later
  pass reaps it through :func:`poll_fast_installs`, which records a failure (so
  the caller falls back to ``steam://install``) and interrupts a run whose
  output has stalled - most likely a login prompt nobody will ever answer,
  sitting there with Steam shut down.

The installer closes Steam to do its work, so it is refused outright while a
game is running or another app is mid-update (the AoE2 corruption case).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import sys
import time

from steam_backlog_enforcer import config as _config
from steam_backlog_enforcer._desktop_env import desktop_user_cmd, resolve_desktop_user
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._steam_restart_guard import game_is_running
from steam_backlog_enforcer._steam_state import (
    STEAMAPPS_PATH,
    steam_update_in_progress,
)

logger = logging.getLogger(__name__)

_INSTALLER = Path("src", "steam-game-installer", "run.sh")
_INSTALLER_LOG = "~/.local/state/steam-game-installer/latest.log"
# Depot content only: the app itself is ours to choose, the language is not
# worth a prompt nobody is there to answer.
_LANGUAGE = "english"
# depotdownloader prints a line per finished chunk, so a healthy download is
# never silent this long; a login prompt waiting on /dev/null is.
STALL_SECONDS = 15 * 60


@dataclass
class _DetachedRun:
    """A daemon-spawned installer run, kept so it can be reaped."""

    app_id: int
    proc: subprocess.Popen[bytes]
    log_path: Path


_RUNS: list[_DetachedRun] = []
# Apps whose installer run failed in this process. They go straight to the
# steam:// fallback from then on, so a broken login cannot close Steam on
# every 3-second pass.
_FAILED: set[int] = set()


def _installer_path(user: str | None) -> Path | None:
    """steam-game-installer's ``run.sh`` in the desktop user's home, if present.

    Resolved from the passwd entry rather than ``Path.home()``: the daemon runs
    as root, and the installer, its venv and its credentials are per-user.
    """
    try:
        home = Path(pwd.getpwnam(user).pw_dir) if user else Path.home()
    except KeyError:
        return None
    path = home / _INSTALLER
    return path if path.is_file() else None


def _steam_account_name() -> str | None:
    """The account Steam itself last signed in with, from ``loginusers.vdf``.

    Read from Steam's own state rather than a copy in the enforcer config, so
    it cannot drift from the account that actually owns the games.
    """
    path = STEAMAPPS_PATH.parent / "config" / "loginusers.vdf"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'"AccountName"\s+"([^"]+)"', content)
    return match.group(1) if match else None


def _refusal(app_id: int) -> str | None:
    """Why closing Steam right now would do damage, or None if it is safe."""
    if game_is_running():
        return "a game is running and closing Steam would kill it"
    if steam_update_in_progress(exclude_app_id=app_id):
        return (
            "another Steam download is in progress and closing Steam could corrupt it"
        )
    return None


def _build_cmd(installer: Path, app_id: int, user: str | None) -> list[str]:
    """The installer invocation, dropped to the desktop user when root."""
    cmd = [
        str(installer),
        # install.sh reaches for yay; dependencies are installed once, by hand.
        "--no-deps",
        "--appid",
        str(app_id),
        "--yes",
        "--language",
        _LANGUAGE,
        # Finishes the manifest from depotdownloader's own data, under the same
        # fail-closed checks: no second login, no 70 GB re-hash by steamcmd.
        "--skip-steamcmd",
    ]
    account = _steam_account_name()
    if account:
        cmd += ["--username", account]
    return desktop_user_cmd(cmd, user)


def is_fast_installing(app_id: int) -> bool:
    """Whether this process has a live detached installer run for *app_id*."""
    return any(run.app_id == app_id for run in _RUNS)


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
        _FAILED.add(run.app_id)
        logger.warning(
            "steam-game-installer failed for AppID=%d (exit %d); falling back "
            "to Steam's own download. Log: %s",
            run.app_id,
            returncode,
            run.log_path,
        )


def _spawn_detached(cmd: list[str], app_id: int) -> None:
    """Start the installer in its own session, output to a log file."""
    log_path = _config.CONFIG_DIR / "fast_install.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The unit is KillMode=control-group: restarting the daemon would SIGTERM
    # an installer left in its cgroup, skipping the `finally` that restarts
    # Steam. A transient scope moves it out; --scope execs in place, so the
    # Popen pid below is still the session leader killpg needs.
    if os.geteuid() == 0 and shutil.which("systemd-run"):
        cmd = ["systemd-run", "--scope", "--quiet", "--collect", *cmd]
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _RUNS.append(_DetachedRun(app_id, proc, log_path))
    logger.info("Started steam-game-installer for AppID=%d (log: %s)", app_id, log_path)


def fast_install(app_id: int, label: str) -> bool:
    """Install *app_id* with steam-game-installer.

    Returns:
        True if the game was installed (foreground) or the run was started
        (detached); False if the caller should fall back to Steam's download.
    """
    if app_id in _FAILED:
        return False
    user = resolve_desktop_user()
    installer = _installer_path(user)
    if installer is None:
        logger.warning("steam-game-installer not found; using Steam's download.")
        return False
    reason = _refusal(app_id)
    if reason is not None:
        _echo(f"  Fast install of {label} skipped: {reason}.")
        return False

    cmd = _build_cmd(installer, app_id, user)
    if not sys.stdin.isatty():
        _spawn_detached(cmd, app_id)
        return True

    _echo(f"  Fast-installing {label} with steam-game-installer (Steam will close)...")
    returncode = subprocess.run(cmd, check=False).returncode
    if returncode == 0:
        return True
    _FAILED.add(app_id)
    _echo(
        f"  steam-game-installer failed (exit {returncode}); falling back to "
        f"Steam's own download. Log: {_INSTALLER_LOG}"
    )
    return False
