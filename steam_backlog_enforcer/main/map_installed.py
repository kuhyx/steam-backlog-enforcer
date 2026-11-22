"""``map-installed``: the installer's ``--map-installed --apply``, behind friction.

The apply closes Steam (``flow.prepare_steam``: Steam rewrites config.vdf on
exit), maps each game the decision proves safe to the native Proton, and
starts Steam again. Closing Steam under a running game would kill it, so this
refuses while one runs. The web server checks the ids, the phrase (it names
how many games) and the guard before a job exists (``_web_jobs``); this
re-checks all three inside the job. The installer gets exactly the ids the
phrase counted, never "everything".
"""

from __future__ import annotations

import subprocess
import threading
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._command_params import InvalidParamsError
from steam_backlog_enforcer._compat_view import checked_appids
from steam_backlog_enforcer._desktop_env import resolve_desktop_user
from steam_backlog_enforcer._fast_install_cmd import (
    build_map_installed_cmd,
    installer_path,
)
from steam_backlog_enforcer._prompter import PromptAbortedError, confirm_phrase
from steam_backlog_enforcer._steam_restart_guard import (
    GAME_RUNNING_JOB_MSG,
    game_is_running,
)
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.main._install_target import require_installer

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

# Closing Steam may take steamctl.SHUTDOWN_TIMEOUT (60 s), then the mapping
# and the restart: well past the dry run's 50 s.
APPLY_TIMEOUT_SECONDS: Final = 180


def stream_installer(cmd: list[str], *, timeout: float) -> int:
    """Run *cmd*, echo each output line as it comes, return its exit code.

    Streamed, so the job page shows Steam closing and each game mapped live.
    A timer kills it at *timeout* even while it still holds stdout open; a
    killed run returns non-zero.
    """
    killed = threading.Event()
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    ) as proc:

        def kill() -> None:
            killed.set()
            proc.kill()

        timer = threading.Timer(timeout, kill)
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout or ():
                _echo(f"  {line.rstrip()}")
            code = proc.wait()
        finally:
            timer.cancel()
    if killed.is_set():
        _echo(f"  Killed after {timeout:.0f} s.")
        return code or 1
    return code


def run_map_installed(raw_appids: str | None) -> list[int]:
    """Map *raw_appids* (or every game that would change), after guard and phrase.

    Returns:
        The app ids handed to the installer.

    Raises:
        JobError: ``game_running`` while a game runs; ``invalid_params`` when
            the ids are no longer valid; ``op_failed`` when the installer is
            missing or exits non-zero.
        PromptAbortedError: The phrase was not typed exactly.
    """
    if game_is_running():
        raise JobError(GAME_RUNNING_JOB_MSG, code="game_running")
    try:
        appids = checked_appids(raw_appids)
    except InvalidParamsError as exc:
        raise JobError(str(exc), code="invalid_params") from None
    count = len(appids)
    question = f"Close Steam and map {count} games to the native Proton?"
    if not confirm_phrase("map-installed", question, appid_count=count):
        msg = "Aborted."
        raise PromptAbortedError(msg)
    installer = require_installer(installer_path())
    cmd = build_map_installed_cmd(installer, resolve_desktop_user(), appids)
    code = stream_installer(cmd, timeout=APPLY_TIMEOUT_SECONDS)
    if code:
        msg = f"map-installed failed (installer exit {code})."
        raise JobError(msg, code="op_failed")
    return appids


def cmd_map_installed(_config: Config, _state: State) -> None:
    """``./run.sh map-installed``: every installed game that would change."""
    run_map_installed(None)
