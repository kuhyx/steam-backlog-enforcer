"""Hide / unhide games in the Steam library via sharedconfig.vdf.

Steam stores per-app settings (including the "hidden" flag) in
``userdata/<userid>/7/remote/sharedconfig.vdf`` under the path:

    UserRoamingConfigStore > Software > Valve > Steam > apps > <appid>

Setting ``"hidden" "1"`` makes the game invisible in the default
library view.  This module provides functions to bulk-hide every owned
game *except* the currently assigned one, and to unhide them all when
enforcement is lifted.

Steam must be restarted (or not running) for the changes to take effect,
because it overwrites the file on exit.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Steam user-data paths.
_STEAM_DIR = Path.home() / ".local" / "share" / "Steam"
_USERDATA_DIR = _STEAM_DIR / "userdata"
_SHARED_CONFIG_REL = Path("7") / "remote" / "sharedconfig.vdf"


# ──────────────────────────────────────────────────────────────
# Minimal VDF parser / writer
# ──────────────────────────────────────────────────────────────


def _parse_vdf(text: str) -> dict[str, Any]:
    """Parse a Valve VDF text file into nested dicts.

    Only handles the subset used by sharedconfig.vdf (string values and
    nested sections).
    """
    tokens: list[str] = []
    for m in re.finditer(r'"([^"]*)"|\{|\}', text):
        if m.group(1) is not None:
            tokens.append(m.group(1))
        else:
            tokens.append(m.group(0))  # "{" or "}"
    idx = 0

    def _parse_obj() -> dict[str, Any]:
        nonlocal idx
        obj: dict[str, Any] = {}
        while idx < len(tokens):
            token = tokens[idx]
            if token == "}":  # noqa: S105
                idx += 1
                return obj
            # Key.
            key = token
            idx += 1
            if idx >= len(tokens):
                break
            # Value: either a string or a nested object.
            nxt = tokens[idx]
            if nxt == "{":
                idx += 1
                obj[key] = _parse_obj()
            elif nxt == "}":
                # Key without value right before closing brace — skip.
                obj[key] = ""
                # Don't advance; let the outer loop consume '}'.
            else:
                obj[key] = nxt
                idx += 1
        return obj

    return _parse_obj()


def _write_vdf(data: dict[str, Any], indent: int = 0) -> str:
    """Serialize a nested dict back to VDF text."""
    lines: list[str] = []
    prefix = "\t" * indent

    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f'{prefix}"{key}"')
            lines.append(f"{prefix}{{")
            lines.append(_write_vdf(value, indent + 1))
            lines.append(f"{prefix}}}")
        else:
            lines.append(f'{prefix}"{key}"\t\t"{value}"')

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Discover Steam user IDs on this machine
# ──────────────────────────────────────────────────────────────


def _find_user_dirs() -> list[Path]:
    """Return paths to all numeric userdata directories except '0'."""
    if not _USERDATA_DIR.is_dir():
        return []
    return [p for p in _USERDATA_DIR.iterdir() if p.name.isdigit() and p.name != "0"]


# ──────────────────────────────────────────────────────────────
# Hide / unhide logic
# ──────────────────────────────────────────────────────────────


def _get_apps_section(
    vdf_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Navigate to the ``apps`` dict inside the VDF tree."""
    try:
        steam_section = vdf_data["UserRoamingConfigStore"]["Software"]["Valve"]["Steam"]
        if "apps" not in steam_section:
            steam_section["apps"] = {}
    except (KeyError, TypeError):
        return None
    else:
        result: dict[str, Any] = steam_section["apps"]
        return result


def _hide_games_in_profile(
    config_path: Path,
    user_dir: Path,
    owned_app_ids: list[int],
    allowed_app_id: int | None,
) -> int:
    """Hide games in a single Steam user profile.

    Args:
        config_path: Path to the sharedconfig.vdf file.
        user_dir: Path to the user's data directory.
        owned_app_ids: List of owned game app IDs.
        allowed_app_id: App ID of the game that should remain visible.

    Returns:
        Number of games hidden in this profile.
    """
    # Back up the original.
    backup = config_path.with_suffix(".vdf.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)

    text = config_path.read_text(encoding="utf-8")
    vdf_data = _parse_vdf(text)
    apps = _get_apps_section(vdf_data)
    if apps is None:
        logger.warning("Could not find apps section in %s", config_path)
        return 0

    hidden_count = _apply_hide_flags(apps, owned_app_ids, allowed_app_id)

    output = _write_vdf(vdf_data) + "\n"
    config_path.write_text(output, encoding="utf-8")
    _fix_ownership(config_path, user_dir)

    logger.info("Hidden %d games in profile %s", hidden_count, user_dir.name)
    return hidden_count


def _apply_hide_flags(
    apps: dict[str, Any],
    owned_app_ids: list[int],
    allowed_app_id: int | None,
) -> int:
    """Set hidden flags on all games except the allowed one.

    Args:
        apps: The VDF apps section dict.
        owned_app_ids: List of owned app IDs.
        allowed_app_id: App ID to keep visible.

    Returns:
        Number of games newly hidden.
    """
    hidden_count = 0
    for app_id in owned_app_ids:
        sid = str(app_id)
        if app_id == allowed_app_id:
            if sid in apps and isinstance(apps[sid], dict):
                apps[sid].pop("hidden", None)
            continue

        if sid not in apps or not isinstance(apps[sid], dict):
            apps[sid] = {}
        if apps[sid].get("hidden") != "1":
            apps[sid]["hidden"] = "1"
            hidden_count += 1
    return hidden_count


def hide_other_games(
    owned_app_ids: list[int],
    allowed_app_id: int | None,
) -> int:
    """Hide every owned game except *allowed_app_id* in the Steam library.

    Modifies ``sharedconfig.vdf`` for every local Steam user profile.
    Steam must be restarted for changes to take effect.

    Returns the number of games that were hidden.
    """
    user_dirs = _find_user_dirs()
    if not user_dirs:
        logger.warning("No Steam userdata directories found.")
        return 0

    total_hidden = 0

    for user_dir in user_dirs:
        config_path = user_dir / _SHARED_CONFIG_REL
        if not config_path.exists():
            logger.debug("No sharedconfig.vdf in %s", user_dir.name)
            continue

        total_hidden += _hide_games_in_profile(
            config_path, user_dir, owned_app_ids, allowed_app_id
        )

    return total_hidden


def unhide_all_games(owned_app_ids: list[int]) -> int:
    """Remove the hidden flag from all owned games.

    Returns the number of games that were unhidden.
    """
    user_dirs = _find_user_dirs()
    total = 0

    for user_dir in user_dirs:
        config_path = user_dir / _SHARED_CONFIG_REL
        if not config_path.exists():
            continue

        text = config_path.read_text(encoding="utf-8")
        vdf_data = _parse_vdf(text)
        apps = _get_apps_section(vdf_data)
        if apps is None:
            continue

        count = 0
        for app_id in owned_app_ids:
            sid = str(app_id)
            if sid in apps and isinstance(apps[sid], dict):
                if apps[sid].pop("hidden", None) is not None:
                    count += 1
                # Remove the entry entirely if it's now empty.
                if not apps[sid]:
                    del apps[sid]

        output = _write_vdf(vdf_data) + "\n"
        config_path.write_text(output, encoding="utf-8")
        _fix_ownership(config_path, user_dir)

        logger.info("Unhidden %d games in profile %s", count, user_dir.name)
        total += count

    return total


# ──────────────────────────────────────────────────────────────
# Steam restart helper
# ──────────────────────────────────────────────────────────────


def restart_steam() -> None:
    """Gracefully restart the Steam client.

    Sends ``steam -shutdown``, waits, then launches again with ``-silent``.
    """
    real_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    logger.info("Restarting Steam client...")

    # Shut down Steam gracefully.
    try:
        _run_as_user(["steam", "-shutdown"], real_user)
    except FileNotFoundError:
        logger.warning("Steam executable not found for restart.")
        return

    # Wait for Steam to exit.
    import time

    _pgrep = shutil.which("pgrep") or "/usr/bin/pgrep"
    for _ in range(30):
        result = subprocess.run(
            [_pgrep, "-f", "steam.sh"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            break
        time.sleep(1)

    # Relaunch silently.
    with contextlib.suppress(FileNotFoundError):
        _run_as_user(["steam", "-silent"], real_user)


def _run_as_user(cmd: list[str], user: str | None) -> None:
    """Run a command, dropping to *user* if currently root."""
    if os.geteuid() == 0 and user and user != "root":
        try:
            pw = pwd.getpwnam(user)
            uid = pw.pw_uid
        except KeyError:
            uid = 1000

        dbus_default = f"unix:path=/run/user/{uid}/bus"
        dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", dbus_default)
        xauth = os.environ.get("XAUTHORITY", f"/home/{user}/.Xauthority")
        full_cmd = [
            "sudo",
            "-u",
            user,
            "env",
            f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
            f"XAUTHORITY={xauth}",
            f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
            *cmd,
        ]
    else:
        full_cmd = cmd

    subprocess.Popen(
        full_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _fix_ownership(path: Path, user_dir: Path) -> None:
    """If running as root, chown the file to the user who owns user_dir."""
    if os.geteuid() != 0:
        return
    try:
        stat = user_dir.stat()
        os.chown(path, stat.st_uid, stat.st_gid)
    except OSError:
        pass
