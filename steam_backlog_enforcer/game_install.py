"""Game installation and uninstallation management."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# Real Steam directory — used as a safety check to block destructive
# operations that leak through during testing.
_REAL_STEAMAPPS = Path("~/.local/share/Steam/steamapps").expanduser()


def _assert_not_real_steam(path: Path) -> None:
    """Raise if *path* is inside the real Steam directory.

    Defence-in-depth guard: even if test fixtures fail to
    redirect ``STEAMAPPS_PATH``, destructive operations
    (uninstall, rmtree, unlink) will refuse to touch real files.
    """
    try:
        path.resolve().relative_to(_REAL_STEAMAPPS.resolve())
    except ValueError:
        return  # path is NOT under real Steam — safe to proceed
    if STEAMAPPS_PATH.resolve() == _REAL_STEAMAPPS.resolve():
        msg = (
            f"SAFETY: refusing destructive operation on real Steam path "
            f"{path!s} — STEAMAPPS_PATH was not redirected by test fixtures"
        )
        raise RuntimeError(msg)


def _echo(msg: str = "", *, end: str = "\n", flush: bool = False) -> None:
    """Write user-facing CLI output to stdout.

    Args:
        msg: Text to output.
        end: String appended after the message.
        flush: Whether to flush stdout immediately.
    """
    sys.stdout.write(msg + end)
    if flush:
        sys.stdout.flush()


# Steam infrastructure app IDs that should NEVER be uninstalled.
PROTECTED_APP_IDS = {
    228980,  # Steamworks Common Redistributables
    1070560,  # Steam Linux Runtime 1.0 (scout)
    1391110,  # Steam Linux Runtime 2.0 (soldier)
    1628350,  # Steam Linux Runtime 3.0 (sniper)
    961940,  # Steam Linux Runtime (legacy)
    # Proton versions (never uninstall these)
    858280,  # Proton 3.7 (Beta)
    930400,  # Proton 3.16 (Beta)
    1054830,  # Proton 4.2
    1113280,  # Proton 4.11
    1245040,  # Proton 5.0
    1420170,  # Proton 5.13
    1580130,  # Proton 6.3
    1887720,  # Proton 7.0
    2230260,  # Proton 7.0 (alt)
    2348590,  # Proton 8.0
    2805730,  # Proton 9.0
    3201940,  # Proton 9.0 (alt)
    3658110,  # Proton 10.0
    2180100,  # Proton Hotfix
    1493710,  # Proton Experimental
    1161040,  # Proton BattlEye Runtime
    1007020,  # Proton EasyAntiCheat Runtime
    # Games allowed to be installed anytime
    3949040,  # RV There Yet?
    2252570,
    220200,
}

STEAMAPPS_PATH = Path("~/.local/share/Steam/steamapps").expanduser()


def _trigger_steam_install(app_id: int, label: str) -> bool:
    """Ask Steam to install a game via the ``steam://install`` URI.

    Returns True if the URI handler was invoked successfully.
    """
    xdg_open = shutil.which("xdg-open") or "/usr/bin/xdg-open"
    try:
        subprocess.run(
            [xdg_open, f"steam://install/{app_id}"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    else:
        logger.info("Triggered Steam install for %s via protocol handler", label)
        return True


# ──────────────────────────────────────────────────────────────
# Game install management
# ──────────────────────────────────────────────────────────────


def _get_real_user() -> str | None:
    """Get the real (non-root) user when running under sudo."""
    return os.environ.get("SUDO_USER") or os.environ.get("USER")


def _get_uid_gid_for_user(username: str) -> tuple[int, int]:
    """Get (uid, gid) for a username."""
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return 1000, 1000
    else:
        return pw.pw_uid, pw.pw_gid


def is_game_installed(app_id: int) -> bool:
    """Check if a game is installed by looking for its appmanifest.

    A manifest with StateFlags != 4 (FullyInstalled) means the game is
    still downloading or queued, which still counts as "install triggered".
    """
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    return manifest.exists()


def _ensure_steam_running() -> None:
    """Start the Steam client if it is not already running."""
    # Check if any steam process is running (main client, not just helpers).
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-f", "steam.sh"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            logger.debug("Steam client already running")
            return
    except FileNotFoundError:
        pass

    real_user = _get_real_user()
    logger.info("Starting Steam client...")

    try:
        if os.geteuid() == 0 and real_user and real_user != "root":
            uid, _ = _get_uid_gid_for_user(real_user)
            dbus_default = f"unix:path=/run/user/{uid}/bus"
            dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", dbus_default)
            xauth_default = f"/home/{real_user}/.Xauthority"
            xauth = os.environ.get("XAUTHORITY", xauth_default)
            cmd = [
                "sudo",
                "-u",
                real_user,
                "env",
                f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
                f"XAUTHORITY={xauth}",
                f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
                "steam",
                "-silent",
            ]
        else:
            cmd = ["steam", "-silent"]

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give Steam time to initialize and start scanning manifests.
        time.sleep(15)
    except FileNotFoundError:
        logger.exception("Steam executable not found")


def install_game(
    app_id: int,
    game_name: str,
    steam_id: str,
    *,
    use_steam_protocol: bool = False,
) -> bool:
    """Install a game by triggering a Steam download.

    When *use_steam_protocol* is True the ``steam://install`` URI handler
    is used, which lets Steam determine the correct install directory from
    its own metadata.  This avoids mismatches between the display name and
    the canonical ``installdir`` that can cause "Missing game executable"
    errors.  Falls back to writing a fabricated appmanifest if the URI
    handler is unavailable.

    When *use_steam_protocol* is False (the default) a minimal
    appmanifest with StateFlags=1026 is written directly.  This is
    suitable for non-interactive / daemon contexts where opening a Steam
    dialog is undesirable.

    Args:
        app_id: Steam application ID.
        game_name: Human-readable game name.
        steam_id: Steam64 ID of the account that owns the game.
        use_steam_protocol: Prefer the ``steam://install`` URI handler.

    Returns True if the install was triggered successfully.
    """
    label = game_name or f"AppID={app_id}"

    if is_game_installed(app_id):
        logger.info("Game already installed: %s", label)
        return True

    if use_steam_protocol:
        _ensure_steam_running()
        if _trigger_steam_install(app_id, label):
            return True
        logger.debug("steam:// protocol failed; falling back to manifest")

    # Build a minimal appmanifest.  StateFlags 1026 = UpdateRequired (2) +
    # UpdateStarted (1024), which tells Steam "this app needs downloading".
    manifest_content = (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{app_id}"\n'
        '\t"universe"\t\t"1"\n'
        f'\t"name"\t\t"{game_name}"\n'
        '\t"StateFlags"\t\t"1026"\n'
        f'\t"installdir"\t\t"{game_name}"\n'
        '\t"LastUpdated"\t\t"0"\n'
        '\t"LastPlayed"\t\t"0"\n'
        '\t"SizeOnDisk"\t\t"0"\n'
        '\t"StagingSize"\t\t"0"\n'
        '\t"buildid"\t\t"0"\n'
        f'\t"LastOwner"\t\t"{steam_id}"\n'
        '\t"UpdateResult"\t\t"0"\n'
        '\t"BytesToDownload"\t\t"0"\n'
        '\t"BytesDownloaded"\t\t"0"\n'
        '\t"BytesToStage"\t\t"0"\n'
        '\t"BytesStaged"\t\t"0"\n'
        '\t"TargetBuildID"\t\t"0"\n'
        '\t"AutoUpdateBehavior"\t\t"0"\n'
        '\t"AllowOtherDownloadsWhileRunning"\t\t"0"\n'
        '\t"ScheduledAutoUpdate"\t\t"0"\n'
        '\t"InstalledDepots"\n'
        "\t{\n"
        "\t}\n"
        '\t"UserConfig"\n'
        "\t{\n"
        "\t}\n"
        '\t"MountedConfig"\n'
        "\t{\n"
        "\t}\n"
        "}\n"
    )

    manifest_path = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"

    try:
        with manifest_path.open("w", encoding="utf-8") as fh:
            fh.write(manifest_content)

        # Fix ownership so the Steam client (running as the real user) can
        # read and update the manifest.
        real_user = _get_real_user()
        if os.geteuid() == 0 and real_user and real_user != "root":
            uid, gid = _get_uid_gid_for_user(real_user)
            os.chown(manifest_path, uid, gid)

        logger.info("Created appmanifest for %s — Steam will auto-download", label)
    except OSError:
        logger.exception("Failed to create appmanifest for %s", label)
        return False

    # Make sure Steam is running so it picks up the manifest.
    _ensure_steam_running()

    return True


# ──────────────────────────────────────────────────────────────
# Game uninstall management
# ──────────────────────────────────────────────────────────────


def get_installed_games() -> list[tuple[int, str]]:
    """Parse appmanifest files to find installed games.

    Returns: list of (app_id, game_name) tuples.
    """
    installed: list[tuple[int, str]] = []

    for manifest_file in STEAMAPPS_PATH.glob("appmanifest_*.acf"):
        with contextlib.suppress(OSError):
            content = manifest_file.read_text(encoding="utf-8")
            app_id_match = re.search(r'"appid"\s+"(\d+)"', content)
            name_match = re.search(r'"name"\s+"([^"]+)"', content)
            if app_id_match:
                app_id = int(app_id_match.group(1))
                name = name_match.group(1) if name_match else f"Unknown ({app_id})"
                installed.append((app_id, name))

    installed.sort(key=lambda x: x[1].lower())
    return installed


def _read_install_dir(manifest: Path) -> Path | None:
    """Read installdir from a game's appmanifest file."""
    if not manifest.exists():
        return None
    try:
        content = manifest.read_text(encoding="utf-8")
        match = re.search(r'"installdir"\s+"([^"]+)"', content)
        if match:
            return STEAMAPPS_PATH / "common" / match.group(1)
    except OSError:
        pass
    return None


def _remove_manifest(manifest: Path, game_name: str, app_id: int) -> bool:
    """Remove a game manifest file.

    Args:
        manifest: Path to the appmanifest file.
        game_name: Human-readable game name for logging.
        app_id: Steam application ID.
    """
    _assert_not_real_steam(manifest)
    try:
        if manifest.exists():
            manifest.unlink()
            logger.info(
                "Removed manifest for %s (AppID=%d)", game_name or app_id, app_id
            )
    except OSError:
        logger.exception("Failed to remove manifest for AppID=%d", app_id)
        return False
    return True


def _remove_game_dirs(install_dir: Path | None, app_id: int) -> bool:
    """Remove game installation directory and cache directories.

    Args:
        install_dir: Path to the game's install directory, or None.
        app_id: Steam application ID.
    """
    success = True
    if install_dir and install_dir.is_dir():
        _assert_not_real_steam(install_dir)
        try:
            shutil.rmtree(install_dir)
            logger.info("Removed game files: %s", install_dir)
        except OSError:
            logger.exception("Failed to remove game dir %s", install_dir)
            success = False

    for subdir in ("shadercache", "compatdata"):
        cache_path = STEAMAPPS_PATH / subdir / str(app_id)
        if cache_path.is_dir():
            _assert_not_real_steam(cache_path)
            with contextlib.suppress(OSError):
                shutil.rmtree(cache_path)
                logger.debug("Removed %s/%d", subdir, app_id)

    return success


def uninstall_game(app_id: int, game_name: str = "") -> bool:
    """Uninstall a single game by removing its manifest and game files.

    Uses direct file removal instead of ``steam://uninstall`` URI to avoid
    GUI popups and to work when Steam is not running.
    """
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    install_dir = _read_install_dir(manifest)
    success = _remove_manifest(manifest, game_name, app_id)
    if not _remove_game_dirs(install_dir, app_id):
        success = False
    return success


def uninstall_other_games(allowed_app_id: int | None) -> int:
    """Uninstall all installed games except the assigned one and protected IDs.

    Returns: number of games uninstalled.
    """
    installed = get_installed_games()
    count = 0

    for app_id, name in installed:
        if app_id == allowed_app_id:
            logger.info("KEEPING assigned game: %s (AppID=%d)", name, app_id)
            continue
        if app_id in PROTECTED_APP_IDS:
            logger.debug("Skipping protected: %s (AppID=%d)", name, app_id)
            continue

        logger.info("UNINSTALLING: %s (AppID=%d)", name, app_id)
        if uninstall_game(app_id, name):
            count += 1

    return count
