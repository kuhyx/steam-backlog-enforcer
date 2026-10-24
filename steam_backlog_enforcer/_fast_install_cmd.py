"""How steam-game-installer is invoked: where it lives, as whom, with what argv.

Split out of :mod:`_fast_install`, which runs and reaps the installer; this
half only decides the command line, every choice it would otherwise prompt for
pinned in advance.
"""

from __future__ import annotations

from pathlib import Path
import pwd
import re

from steam_backlog_enforcer._desktop_env import desktop_user_cmd
from steam_backlog_enforcer._steam_state import STEAMAPPS_PATH

_INSTALLER = Path("src", "steam-game-installer", "run.sh")

# Depot content only: the app itself is ours to choose, the language is not
# worth a prompt nobody is there to answer.
_LANGUAGE = "english"


def installer_path(user: str | None) -> Path | None:
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


def build_cmd(installer: Path, app_id: int, user: str | None) -> list[str]:
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
    account = steam_account_name()
    if account:
        cmd += ["--username", account]
    return desktop_user_cmd(cmd, user)
