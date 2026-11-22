"""How the installer (``steam_installer``) is invoked: where, as whom, what argv.

Split out of :mod:`_fast_install`, which runs and reaps the installer; this
half only decides the command line, every choice it would otherwise prompt for
pinned in advance.
"""

from __future__ import annotations

from pathlib import Path
import re

from steam_backlog_enforcer._desktop_env import desktop_user_cmd
from steam_backlog_enforcer._steam_state import STEAMAPPS_PATH

# The installer ships in this repo (``steam_installer``, a sibling package).
# Tests repoint this at a missing file: it always exists here, and a real run
# closes the user's Steam.
_INSTALLER = Path(__file__).resolve().parents[1] / "steam_installer" / "cli.py"

# The interpreter the daemon itself runs under (see the unit's ExecStart). The
# installer needs ``kuhy_credit``, which lives in the desktop user's site.
_PYTHON = "/usr/bin/python3"

# Depot content only: the app itself is ours to choose, the language is not
# worth a prompt nobody is there to answer.
_LANGUAGE = "english"


def installer_path() -> Path | None:
    """The installer's ``cli.py`` inside this checkout, if present.

    A checkout is the same for every user, so unlike the old external clone
    there is no per-user lookup.
    """
    return _INSTALLER if _INSTALLER.is_file() else None


def steam_account_name() -> str | None:
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


def build_cmd(
    installer: Path,
    app_id: int,
    user: str | None,
    *,
    valve_proton: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """The installer invocation, dropped to the desktop user when root.

    Launched as ``python3 -m steam_installer.cli`` with the checkout on
    ``PYTHONPATH``: ``sudo`` resets the environment, so it is named in the argv.
    *valve_proton* keeps the game on Valve's default Proton; *dry_run* only
    reports what the installer would do.
    """
    cmd = [
        "env",
        f"PYTHONPATH={installer.parents[1]}",
        _PYTHON,
        "-m",
        "steam_installer.cli",
        "--appid",
        str(app_id),
        "--yes",
        "--language",
        _LANGUAGE,
    ]
    if valve_proton:
        cmd.append("--valve-proton")
    if dry_run:
        cmd.append("--dry-run")
    account = steam_account_name()
    if account:
        cmd += ["--username", account]
    return desktop_user_cmd(cmd, user)


def build_repair_ghosts_cmd(installer: Path, user: str | None) -> list[str]:
    """The installer's ``--repair-ghosts`` run, dropped to the desktop user.

    No AppID: it scans every library for the fake manifests anonymous
    steamcmd left and clears only the cold ones (``DOCS-steam-installer.md``).
    """
    cmd = [
        "env",
        f"PYTHONPATH={installer.parents[1]}",
        _PYTHON,
        "-m",
        "steam_installer.cli",
        "--repair-ghosts",
    ]
    return desktop_user_cmd(cmd, user)
