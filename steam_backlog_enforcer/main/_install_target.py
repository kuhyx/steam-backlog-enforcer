"""Which game ``install`` may touch, and the installer's dry run.

The web ``install`` takes a target the way the installer does (AppID, Steam
URL or name), but the enforcer resolves it, inside the set of games allowed
today, before the installer runs. The installer then only ever gets the
checked ``--appid``: handing it the raw text would let its own Steam search
pick an app this check never saw. Names are matched locally, so a refused
game costs no network call and an ambiguous one is a choice, never a guess.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_games
from steam_backlog_enforcer._desktop_env import resolve_desktop_user
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._fast_install_cmd import build_cmd, installer_path
from steam_backlog_enforcer._owned_apps_cache import load_owned_records
from steam_backlog_enforcer._prompter import PromptOption, current_prompter
from steam_backlog_enforcer._whitelist_locking import get_approved_exception_ids
from steam_backlog_enforcer.jobs._errors import JobError
from steam_installer.target import parse_literal

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer.config import Config, State

# The dry run only reads Steam's app cache and library folders; repair-ghosts
# only scans them and renames a few manifests.
_DRY_RUN_TIMEOUT_SECONDS = 50


def install_candidates(config: Config, state: State) -> list[tuple[int, str]]:
    """Every game ``install`` may install today, as ``(app_id, name)``.

    The enforcer's allowed games (assignment first, then manual picks) plus
    the approved exceptions, named from the owned-games records.
    """
    games = allowed_games(state)
    known = {aid for aid, _ in games}
    records = load_owned_records(config.steam_id) or []
    names = {int(r["app_id"]): str(r.get("name") or "") for r in records}
    for app_id in sorted(get_approved_exception_ids() - known):
        games.append((app_id, names.get(app_id, "")))
    return games


def _refuse(text: str) -> JobError:
    """The refusal for a game that is not allowed today."""
    return JobError(f"{text!r} is not a game allowed today.", code="locked")


def resolve_target(text: str, candidates: list[tuple[int, str]]) -> tuple[int, str]:
    """Resolve *text* to one of *candidates*.

    Raises:
        JobError: ``locked`` when the target is not an allowed game.
    """
    literal = parse_literal(text)
    if literal is not None:
        game = next((g for g in candidates if g[0] == literal[0]), None)
        if game is None:
            raise _refuse(text)
        return game
    wanted = text.strip().casefold()
    exact = [g for g in candidates if g[1].casefold() == wanted]
    matches = exact or [g for g in candidates if wanted in g[1].casefold()]
    if not matches:
        raise _refuse(text)
    if len(matches) == 1:
        return matches[0]
    options = [PromptOption(str(aid), name) for aid, name in matches]
    picked = int(current_prompter().choice("Install which game", options))
    return next(g for g in matches if g[0] == picked)


def dry_run_install(app_id: int, name: str, *, valve_proton: bool) -> None:
    """Run the installer's ``--dry-run`` for *app_id* and relay its report.

    Never goes through ``install_game``: no manifest is queued, Steam is not
    closed and there is no ``steam://`` fallback, so it is safe while a game
    is running.

    Raises:
        JobError: ``op_failed`` when the installer is missing or fails.
    """
    installer = require_installer(installer_path())
    cmd = build_cmd(
        installer,
        app_id,
        resolve_desktop_user(),
        valve_proton=valve_proton,
        dry_run=True,
    )
    _echo(f"Dry run for {name or f'AppID={app_id}'}:")
    code = relay_installer(cmd)
    if code:
        msg = f"Dry run failed (installer exit {code})."
        raise JobError(msg, code="op_failed")


def require_installer(installer: Path | None) -> Path:
    """*installer* itself, or the ``op_failed`` refusal when it is missing.

    Raises:
        JobError: ``op_failed`` when the checkout has no installer.
    """
    if installer is None:
        msg = "steam-game-installer is missing from this checkout."
        raise JobError(msg, code="op_failed")
    return installer


def relay_installer(cmd: list[str]) -> int:
    """Run a short, prompt-free installer *cmd*, echo its output, return its exit.

    Used for the read-only ``--dry-run`` and for ``--repair-ghosts``; neither
    downloads, so both fit the same timeout.
    """
    proc = subprocess.run(
        cmd,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=_DRY_RUN_TIMEOUT_SECONDS,
    )
    for line in proc.stdout.splitlines():
        _echo(f"  {line}")
    return proc.returncode
