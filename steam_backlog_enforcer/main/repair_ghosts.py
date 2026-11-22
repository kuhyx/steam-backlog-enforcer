"""``repair-ghosts``: the installer's ``--repair-ghosts``, behind friction.

The installer renames each cold ghost manifest (one that claims "installed"
with nothing on disk) and removes its empty folder; a ghost with staged bytes
is reported and kept. It does not close Steam itself, but it rewrites the
library under a client that may be reading it, so it waits like ``install``
does until no game is running. The web server checks the phrase and the guard
before a job exists (``_web_jobs``); this re-checks both inside the job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._desktop_env import resolve_desktop_user
from steam_backlog_enforcer._fast_install_cmd import (
    build_repair_ghosts_cmd,
    installer_path,
)
from steam_backlog_enforcer._prompter import PromptAbortedError, confirm_phrase
from steam_backlog_enforcer._steam_restart_guard import (
    GAME_RUNNING_JOB_MSG,
    game_is_running,
)
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.main._install_target import relay_installer

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


def cmd_repair_ghosts(_config: Config, _state: State) -> None:
    """Delete the ghost manifests, after the guard and the typed phrase.

    Raises:
        JobError: ``game_running`` while a game runs; ``op_failed`` when the
            installer is missing or exits non-zero.
        PromptAbortedError: The phrase was not typed exactly.
    """
    if game_is_running():
        raise JobError(GAME_RUNNING_JOB_MSG, code="game_running")
    if not confirm_phrase("repair-ghosts", "Delete the ghost install manifests?"):
        msg = "Aborted."
        raise PromptAbortedError(msg)
    installer = installer_path()
    if installer is None:
        msg = "steam-game-installer is missing from this checkout."
        raise JobError(msg, code="op_failed")
    code = relay_installer(build_repair_ghosts_cmd(installer, resolve_desktop_user()))
    if code:
        msg = f"repair-ghosts failed (installer exit {code})."
        raise JobError(msg, code="op_failed")
