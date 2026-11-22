"""Remember the Steam username so every run doesn't ask for it again.

Only the username is ever persisted. Passwords and Steam Guard codes stay
where they belong: with depotdownloader's `-remember-password` login token
(prompted through the pty in `runlog.run_logged`). Writing them to a dotfile would be a downgrade in security over
what Steam's own tooling already does.
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "steam-game-installer"
CONFIG_PATH = CONFIG_DIR / "config"
USERNAME_KEY = "username"
ENV_VAR = "STEAM_USERNAME"


class ConfigError(Exception):
    pass


def load_username() -> str | None:
    """The saved username, or None if nothing has been saved yet."""
    if not CONFIG_PATH.is_file():
        return None
    for line in CONFIG_PATH.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == USERNAME_KEY:
            return value.strip() or None
    return None


def save_username(username: str) -> None:
    """Persist the username at 0600, replacing any previous value."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(f"{USERNAME_KEY}={username}\n")
    # Not a secret, but it names an account; no reason for it to be world-readable.
    CONFIG_PATH.chmod(0o600)


def resolve_username(cli_value: str | None, *, interactive: bool) -> str:
    """--username > $STEAM_USERNAME > saved config > prompt (and save the answer)."""
    if cli_value:
        return cli_value
    env_value = os.environ.get(ENV_VAR, "").strip()
    if env_value:
        return env_value
    saved = load_username()
    if saved:
        return saved
    if not interactive:
        raise ConfigError(
            "No Steam username available. Pass --username, set "
            f"${ENV_VAR}, or run once interactively to save one."
        )
    entered = input("Steam username: ").strip()
    if not entered:
        raise ConfigError("No Steam username entered.")
    save_username(entered)
    return entered
