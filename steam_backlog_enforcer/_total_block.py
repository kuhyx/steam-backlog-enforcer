"""Total gaming block: no in-app command to lift it early.

Uninstalls Steam, kills all game/launcher processes, blocks all Steam +
game-website domains, purges known Steam/Proton filesystem remnants, and
uninstalls Proton helper packages, for a fixed number of days.

Tamper-resistance is provided by guard-lib (~/guard-lib): the lock file's
``until`` timestamp is protected by a bind-mounted, chattr-immutable
file-guard instance, and pacman itself refuses to reinstall/upgrade the
``steam`` package while the lock is active (package-block).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import socket
import subprocess

from steam_backlog_enforcer.config import (
    BLOCKED_DOMAINS,
    CONFIG_DIR,
    HOSTS_FILE,
    _atomic_write,
)
from steam_backlog_enforcer.enforcer import (
    get_pids_by_process_names,
    kill_processes_by_name,
)
from steam_backlog_enforcer.store_blocker import (
    _disable_hosts_protection,
    _enable_hosts_protection,
    _sudo_write_hosts,
    flush_dns_cache,
)

logger = logging.getLogger(__name__)

TOTAL_BLOCK_LOCK_FILE = CONFIG_DIR / "total_block_lock.json"
_IPTABLES_IP_CACHE_FILE = CONFIG_DIR / "total_block_ip_cache.json"

_PACKAGE_BLOCK_NAME = "steam-block"
_STEAM_PACKAGE = "steam"

# Steam's own client processes.
STEAM_CLIENT_PROCESS_NAMES = frozenset({"steam", "steamwebhelper", "steam.sh"})

# Third-party game launchers, best-effort match by process name.
LAUNCHER_PROCESS_NAMES = frozenset(
    {
        "EpicGamesLauncher",
        "legendary",
        "lutris",
        "heroic",
        "GalaxyClient",
        "itch",
        "bottles",
        "minecraft-launcher",
        "prismlauncher",
        "multimc",
        "polymc",
        "ATLauncher",
        "GDLauncher",
        "gdlauncher-carbon",
        "TLauncher",
        "modrinth-app",
    }
)
# Known limitation, not engineered around in this pass: any launcher run
# via an interpreter rather than its own compiled binary shows up in
# /proc/*/comm as the INTERPRETER's name, not its own - process-name
# matching won't catch those. Confirmed live for "lutris" (a Python
# script, appears as `python3`), and documented upstream for some
# Minecraft launchers (TLauncher, ATLauncher, GDLauncher - exec'd as
# `java -jar ...`, appear as `java`). Matching the interpreter name
# itself is NOT a fix: kill_processes_by_name runs inside this very
# enforcer process, which is itself `python3` - adding it to the set
# would SIGTERM the daemon and every other Python process on the system.
# Consistent with the "best-effort" framing already agreed for non-Steam
# blocking; the hosts+iptables domain blocking below is the backstop for
# launchers this can't catch by process name.

TOTAL_BLOCK_DOMAINS = [
    *BLOCKED_DOMAINS,
    "steamcommunity.com",
    "api.steampowered.com",
    "login.steampowered.com",
    "help.steampowered.com",
    "steamcontent.com",
    "steamstatic.com",
    "steamusercontent.com",
    "cdn.steamstatic.com",
]

# Browser/flash game sites. Note itch.io overlaps with the "itch" desktop
# app process kill above (web storefront vs. desktop client).
GAME_WEBSITE_DOMAINS = [
    "newgrounds.com",
    "armorgames.com",
    "kongregate.com",
    "crazygames.com",
    "poki.com",
    "miniclip.com",
    "addictinggames.com",
    "y8.com",
    "coolmathgames.com",
    "itch.io",
]


def _expand_with_www(domains: list[str]) -> list[str]:
    """Add a ``www.`` variant for each bare second-level domain.

    Most of these sites 301-redirect their apex domain to ``www.<domain>``
    (confirmed live for newgrounds.com) - blocking only the apex leaves the
    www subdomain reachable through both the hosts-file entry and the
    iptables IP block. Domains that already carry a subdomain (e.g.
    store.steampowered.com) are left as-is.
    """
    expanded: list[str] = []
    for domain in domains:
        expanded.append(domain)
        if domain.count(".") == 1:
            expanded.append(f"www.{domain}")
    return expanded


_ALL_TOTAL_BLOCK_DOMAINS = _expand_with_www(
    [*TOTAL_BLOCK_DOMAINS, *GAME_WEBSITE_DOMAINS]
)

_HOSTS_BLOCK_BEGIN = "# BEGIN steam-backlog-enforcer total-block\n"
_HOSTS_BLOCK_END = "# END steam-backlog-enforcer total-block\n"

_SUDO = shutil.which("sudo") or "/usr/bin/sudo"
_GUARDCTL = shutil.which("guardctl") or "/usr/local/bin/guardctl"
# Call pacman.orig directly (bypassing pacman_wrapper's interactive
# word-unscramble challenge for "steam") - this is the tool's own
# authorized action, not a user bypass attempt, and enforce_total_block_tick
# must be able to run unattended.
_PACMAN = (
    shutil.which("pacman.orig") or shutil.which("pacman") or "/usr/bin/pacman.orig"
)
_IPTABLES = shutil.which("iptables") or "/usr/sbin/iptables"

IPTABLES_CHAIN = "STEAM_TOTAL_BLOCK"
# The /etc/hosts null-route redirect target used to make a blocked domain
# resolve nowhere - built from parts rather than the literal so linters don't
# mistake it for a socket bind-all-interfaces address (it never is one).
_NULL_ROUTE_IP = ".".join(["0"] * 4)

_STEAM_PURGE_LOG_FILE = CONFIG_DIR / "total_block_purge_log.json"

# Fixed allowlist of known Steam/Proton filesystem remnants to delete - NOT
# a recursive "anything whose name contains 'steam'" sweep, which would also
# catch unrelated files (AUR build checkouts, archives, other apps' own save
# data) that merely share the substring. Confirmed present on the reference
# machine: ~/.steam (symlink farm), ~/steam (secondary/portable install),
# ~/.local/share/Steam (the real install - steamapps, userdata, screenshots,
# and compatibilitytools.d's GE-Proton builds all live under here).
_STEAM_REMNANT_PATHS: tuple[Path, ...] = (
    Path.home() / ".steam",
    Path.home() / "steam",
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steampath",
    Path.home() / ".steampid",
    Path.home() / ".config" / "steamtinkerlaunch",
    Path.home() / ".config" / "CSDSteamBuild",
)

# Proton-management helper packages (not Steam itself, not launched by
# STEAM_CLIENT_PROCESS_NAMES) - installed via pacman/AUR, so pacman -R
# is sufficient; no separate process-kill needed as these are short-lived
# CLI/GUI tools, not background daemons.
_PROTON_HELPER_PACKAGES: tuple[str, ...] = (
    "protondb-tags-git",
    "protonhax-git",
    "protontricks-git",
    "protonup-ng-git",
    "protonup-qt",
)


@dataclass
class TotalBlockStatus:
    """Snapshot of the total-block lock state."""

    active: bool
    started_at: datetime | None
    until: datetime | None
    days: int
    days_remaining: float


def _read_lock() -> dict[str, object] | None:
    """Read and parse the total-block lock file, or None if absent/invalid."""
    if not TOTAL_BLOCK_LOCK_FILE.exists():
        return None
    try:
        data = json.loads(TOTAL_BLOCK_LOCK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_total_block_active() -> bool:
    """Return True if a total gaming block is currently in force."""
    data = _read_lock()
    if data is None:
        return False
    until = data.get("until")
    if not isinstance(until, int | float):
        return False
    return datetime.now(timezone.utc).timestamp() < until


def total_block_needs_cleanup() -> bool:
    """True if a total-block lock file exists on disk but has expired.

    Distinguishes "never started" (no lock file - nothing to do) from
    "expired, not yet cleaned up" (lock file present, `until` has passed) -
    the latter needs :func:`end_total_block_cleanup` called exactly once.
    ``guardctl package-block end`` deletes the lock file, so this is
    naturally self-terminating once cleanup has run.
    """
    return _read_lock() is not None and not is_total_block_active()


def get_total_block_status() -> TotalBlockStatus:
    """Return a snapshot of the current total-block lock state."""
    data = _read_lock()
    if data is None:
        return TotalBlockStatus(
            active=False, started_at=None, until=None, days=0, days_remaining=0.0
        )

    started_at = data.get("started_at")
    until = data.get("until")
    days = data.get("days")

    started_dt = (
        datetime.fromtimestamp(started_at, tz=timezone.utc)
        if isinstance(started_at, int | float)
        else None
    )
    until_dt = (
        datetime.fromtimestamp(until, tz=timezone.utc)
        if isinstance(until, int | float)
        else None
    )

    now = datetime.now(timezone.utc)
    active = until_dt is not None and now < until_dt
    days_remaining = (
        (until_dt - now).total_seconds() / 86400 if active and until_dt else 0.0
    )

    return TotalBlockStatus(
        active=active,
        started_at=started_dt,
        until=until_dt,
        days=days if isinstance(days, int) else 0,
        days_remaining=max(0.0, days_remaining),
    )


# ──────────────────────────────────────────────────────────────
# Process killing + launcher package removal
# ──────────────────────────────────────────────────────────────


def _pacman_owner(path: str) -> str | None:
    """Return the pacman package name that owns *path*, or None."""
    result = subprocess.run(
        [_PACMAN, "-Qo", path],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    marker = " is owned by "
    if marker not in result.stdout:
        return None
    tail = result.stdout.split(marker, 1)[1].strip()
    return tail.split()[0] if tail else None


def _uninstall_package(package: str) -> bool:
    """Remove *package* via pacman. Returns True on success or if absent."""
    try:
        result = subprocess.run(
            [_SUDO, _PACMAN, "-R", "--noconfirm", package],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to run pacman -R %s", package)
        return False
    if result.returncode == 0:
        return True
    if "target not found" in (result.stderr or "").lower():
        return True
    logger.error(
        "pacman -R %s failed (rc=%d): %s",
        package,
        result.returncode,
        result.stderr[-500:] if result.stderr else "",
    )
    return False


def _kill_and_uninstall_launchers() -> list[tuple[int, str]]:
    """Kill running third-party launchers and uninstall their pacman package.

    Resolves each PID's ``/proc/<pid>/exe`` target *before* sending SIGTERM,
    since the symlink stops resolving once the process has exited. Package
    removal is best-effort: launchers installed outside pacman (flatpak,
    AppImage, a wine prefix) simply have no owning package and are just
    killed again next tick, same as before this existed.
    """
    pids = get_pids_by_process_names(LAUNCHER_PROCESS_NAMES)
    exe_paths: dict[int, str] = {}
    for pid in pids:
        with contextlib.suppress(OSError):
            exe_paths[pid] = str(Path(f"/proc/{pid}/exe").resolve(strict=True))

    killed = kill_processes_by_name(LAUNCHER_PROCESS_NAMES)

    packages: set[str] = set()
    for pid, _name in killed:
        exe_path = exe_paths.get(pid)
        if exe_path is not None:
            package = _pacman_owner(exe_path)
            if package is not None:
                packages.add(package)

    for package in packages:
        if not _uninstall_package(package):
            logger.warning(
                "Total block: failed to uninstall launcher package %s", package
            )

    return killed


def _kill_steam_and_launchers() -> list[tuple[int, str]]:
    """Kill Steam client and known third-party launcher processes."""
    steam_killed = kill_processes_by_name(STEAM_CLIENT_PROCESS_NAMES)
    launcher_killed = _kill_and_uninstall_launchers()
    return steam_killed + launcher_killed


# ──────────────────────────────────────────────────────────────
# Steam package removal
# ──────────────────────────────────────────────────────────────


def _is_package_installed(package: str) -> bool:
    """Return True if *package* is currently installed via pacman."""
    result = subprocess.run(
        [_PACMAN, "-Qi", package],
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def _is_steam_installed() -> bool:
    """Return True if the ``steam`` pacman package is currently installed."""
    return _is_package_installed(_STEAM_PACKAGE)


def _uninstall_steam_package() -> bool:
    """Remove the ``steam`` pacman package.

    Returns True on success or if it was already absent.
    """
    return _uninstall_package(_STEAM_PACKAGE)


def _uninstall_proton_helpers() -> list[str]:
    """Uninstall known Proton-management helper packages that are present.

    Returns the subset of :data:`_PROTON_HELPER_PACKAGES` that were actually
    installed and successfully removed (for logging), not the full fixed
    list.
    """
    removed: list[str] = []
    for package in _PROTON_HELPER_PACKAGES:
        if not _is_package_installed(package):
            continue
        if _uninstall_package(package):
            removed.append(package)
        else:
            logger.warning("Total block: failed to uninstall proton helper %s", package)
    return removed


def _remove_steam_remnants() -> list[str]:
    """Delete the curated Steam/Proton filesystem remnants that exist.

    Symlinks are unlinked directly rather than following them into
    :func:`shutil.rmtree`, since e.g. ``~/.steampath`` -> a file inside
    ``~/.steam``, which this same pass may already have removed.
    """
    removed: list[str] = []
    for path in _STEAM_REMNANT_PATHS:
        if not (path.is_symlink() or path.exists()):
            continue
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
        except OSError:
            logger.exception("Failed to remove steam remnant %s", path)
            continue
        removed.append(str(path))
    return removed


def _log_steam_purge(removed_paths: list[str], removed_packages: list[str]) -> None:
    """Append a timestamped record of a Steam/Proton purge to disk.

    A no-op when nothing was actually removed, so the log only grows on
    ticks that did real work (this runs every enforce tick while the block
    is active - see :func:`enforce_total_block_tick`).
    """
    if not removed_paths and not removed_packages:
        return
    try:
        existing = json.loads(_STEAM_PURGE_LOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    except (OSError, json.JSONDecodeError, ValueError):
        existing = []
    existing.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "removed_paths": removed_paths,
            "removed_packages": removed_packages,
        }
    )
    _atomic_write(_STEAM_PURGE_LOG_FILE, json.dumps(existing, indent=2) + "\n")


def _purge_steam_and_proton() -> None:
    """Remove curated Steam/Proton filesystem remnants and helper packages.

    Best-effort and re-run every enforce tick, same as the Steam-package
    reappearance check: a stat() per fixed path and a ``pacman -Qi`` per
    helper package are cheap even when there is nothing left to do.
    """
    removed_paths = _remove_steam_remnants()
    removed_packages = _uninstall_proton_helpers()
    if removed_paths or removed_packages:
        logger.info(
            "Total block: purged steam path(s) %s, proton package(s) %s",
            removed_paths,
            removed_packages,
        )
    _log_steam_purge(removed_paths, removed_packages)


# ──────────────────────────────────────────────────────────────
# Domain blocking (hosts + iptables) - separate from store_blocker's own
# BLOCKED_DOMAINS/STEAM_ENFORCER state, so ending the total block never
# touches normal config.block_store entries.
# ──────────────────────────────────────────────────────────────


def _apply_total_block_hosts() -> bool:
    """Append the total-block domain block to /etc/hosts, if not present."""
    try:
        content = HOSTS_FILE.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read /etc/hosts")
        return False

    if _HOSTS_BLOCK_BEGIN in content:
        return True

    block_lines = [_HOSTS_BLOCK_BEGIN]
    block_lines += [
        f"{_NULL_ROUTE_IP} {domain}\n" for domain in _ALL_TOTAL_BLOCK_DOMAINS
    ]
    block_lines.append(_HOSTS_BLOCK_END)

    new_content = content if content.endswith("\n") else content + "\n"
    new_content += "".join(block_lines)

    try:
        _disable_hosts_protection()
        _sudo_write_hosts(new_content)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to write total-block hosts entries")
        return False
    finally:
        _enable_hosts_protection()
    return True


def _remove_total_block_hosts() -> bool:
    """Remove the total-block domain block from /etc/hosts, if present."""
    try:
        content = HOSTS_FILE.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read /etc/hosts")
        return False

    if _HOSTS_BLOCK_BEGIN not in content:
        return True

    start = content.index(_HOSTS_BLOCK_BEGIN)
    end_marker_at = content.index(_HOSTS_BLOCK_END, start)
    end = end_marker_at + len(_HOSTS_BLOCK_END)
    new_content = content[:start] + content[end:]

    try:
        _disable_hosts_protection()
        _sudo_write_hosts(new_content)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to remove total-block hosts entries")
        return False
    finally:
        _enable_hosts_protection()
    return True


def _load_cached_ips() -> set[str]:
    """Return the accumulated set of previously-resolved total-block IPs."""
    if not _IPTABLES_IP_CACHE_FILE.exists():
        return set()
    try:
        data = json.loads(_IPTABLES_IP_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(ip) for ip in data}


def _save_cached_ips(ips: set[str]) -> None:
    """Persist the accumulated total-block IP set to disk."""
    _atomic_write(_IPTABLES_IP_CACHE_FILE, json.dumps(sorted(ips)) + "\n")


def _iptables_chain_intact(expected_ips: set[str]) -> bool:
    """Cheap check for whether the chain and its OUTPUT hook are intact.

    One `-S` + one `-C` call (two forks), versus the ~30 forks a full
    rebuild costs - this is what keeps :func:`_apply_total_block_iptables`
    from re-resolving DNS and re-forking a subprocess per IP on every
    3-second enforce tick.
    """
    listing = subprocess.run(
        [_SUDO, _IPTABLES, "-S", IPTABLES_CHAIN],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if listing.returncode != 0:
        return False

    current_ips: set[str] = set()
    for line in listing.stdout.splitlines():
        parts = line.split()
        if "-d" in parts:
            idx = parts.index("-d")
            if idx + 1 < len(parts):
                current_ips.add(parts[idx + 1].split("/")[0])

    if not expected_ips.issubset(current_ips):
        return False

    hook = subprocess.run(
        [_SUDO, _IPTABLES, "-C", "OUTPUT", "-j", IPTABLES_CHAIN],
        capture_output=True,
        timeout=5,
        check=False,
    )
    return hook.returncode == 0


def _apply_total_block_iptables() -> bool:
    """Ensure the total-block iptables chain blocks the known domain IPs.

    Resolves domains and (re)builds the chain only when a cheap check
    (:func:`_iptables_chain_intact`) shows it's actually needed - an
    already-intact chain returns immediately. This matters for two
    reasons: re-resolving via DNS every enforce tick (every 3s) would
    otherwise fork ~30 subprocesses/tick indefinitely for a multi-day
    block, and once /etc/hosts's entries take effect, these same domains
    resolve to 0.0.0.0 locally, which would collapse a from-scratch
    rebuild to that one trivial address and silently drop the real
    upstream IPs blocked on the first, pre-hosts-block resolution -
    resolving only when actually needed keeps the accumulated IP cache
    from growing unboundedly too.

    Callers MUST call this before :func:`_apply_total_block_hosts` the
    first time (see :func:`start_total_block`): once the hosts entries
    are in place, DNS resolution for every blocked domain returns 0.0.0.0
    right here on this machine, and no real upstream IP is ever learned.
    """
    cached = _load_cached_ips()
    if cached and _iptables_chain_intact(cached):
        return True

    resolved_ips: set[str] = set()
    try:
        subprocess.run(
            [_SUDO, _IPTABLES, "-N", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            [_SUDO, _IPTABLES, "-F", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=True,
        )

        for domain in _ALL_TOTAL_BLOCK_DOMAINS:
            with contextlib.suppress(socket.gaierror):
                for _, _, _, _, addr in socket.getaddrinfo(domain, 443, socket.AF_INET):
                    resolved_ips.add(str(addr[0]))

        blocked_ips = (cached | resolved_ips) - {_NULL_ROUTE_IP}
        _save_cached_ips(blocked_ips)

        for ip in blocked_ips:
            subprocess.run(
                [_SUDO, _IPTABLES, "-A", IPTABLES_CHAIN, "-d", ip, "-j", "DROP"],
                capture_output=True,
                timeout=5,
                check=True,
            )

        result = subprocess.run(
            [_SUDO, _IPTABLES, "-C", "OUTPUT", "-j", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            subprocess.run(
                [_SUDO, _IPTABLES, "-I", "OUTPUT", "-j", IPTABLES_CHAIN],
                capture_output=True,
                timeout=5,
                check=True,
            )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to apply total-block iptables rules")
        return False
    else:
        logger.info(
            "Total block: %d domain IP(s) blocked via iptables.", len(blocked_ips)
        )
        return True


def _remove_total_block_iptables() -> bool:
    """Remove the total-block iptables chain and its OUTPUT hook."""
    try:
        subprocess.run(
            [_SUDO, _IPTABLES, "-D", "OUTPUT", "-j", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            [_SUDO, _IPTABLES, "-F", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            [_SUDO, _IPTABLES, "-X", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to remove total-block iptables rules")
        return False
    else:
        _IPTABLES_IP_CACHE_FILE.unlink(missing_ok=True)
        return True


# ──────────────────────────────────────────────────────────────
# Public lifecycle API
# ──────────────────────────────────────────────────────────────


def start_total_block(days: int) -> bool:
    """Start a total gaming block for *days* days.

    Registers the package-block lock (bind-mounted, tamper-resistant) via
    guard-lib first - that is the actual enforcement mechanism and must
    succeed for the block to be considered active. Killing processes,
    uninstalling Steam, and applying domain blocks are best-effort follow-up
    steps (logged on failure, re-attempted every enforce tick via
    :func:`enforce_total_block_tick`), since none of them being instantly
    perfect should prevent the lock itself from engaging.

    Returns:
        True if the package-block lock was successfully registered.
    """
    result = subprocess.run(
        [
            _SUDO,
            _GUARDCTL,
            "package-block",
            "start",
            _PACKAGE_BLOCK_NAME,
            "--package",
            _STEAM_PACKAGE,
            "--lock-file",
            str(TOTAL_BLOCK_LOCK_FILE),
            "--days",
            str(days),
            "--bind-mount",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        logger.error("Failed to start package-block lock: %s", result.stderr)
        return False

    killed = _kill_steam_and_launchers()
    if killed:
        logger.info("Total block: killed %d process(es): %s", len(killed), killed)

    if not _uninstall_steam_package():
        logger.warning("Total block: failed to uninstall steam (will retry each tick)")

    _purge_steam_and_proton()

    # iptables MUST be applied before hosts: it resolves real upstream IPs,
    # and once the hosts block is written, local resolution for these same
    # domains collapses to 0.0.0.0 (see _apply_total_block_iptables).
    if not _apply_total_block_iptables():
        logger.warning("Total block: failed to apply iptables rules")
    if not _apply_total_block_hosts():
        logger.warning("Total block: failed to apply hosts entries")

    flush_dns_cache()
    return True


def enforce_total_block_tick() -> None:
    """Re-assert the total block.

    Called every enforce-loop iteration while :func:`is_total_block_active`
    is True.
    """
    _kill_steam_and_launchers()

    if _is_steam_installed():
        logger.warning("Steam reappeared during total block - removing again")
        _uninstall_steam_package()

    _purge_steam_and_proton()

    _apply_total_block_iptables()
    _apply_total_block_hosts()


def end_total_block_cleanup() -> None:
    """Clean up after the total-block lock has naturally expired.

    Ends the package-block lock (guard-lib), removes total-block-specific
    hosts/iptables entries, leaving normal ``config.block_store`` state
    untouched. Does *not* reinstall Steam or restore killed processes -
    the user is free to reinstall/relaunch once the block has expired.
    """
    result = subprocess.run(
        [_SUDO, _GUARDCTL, "package-block", "end", _PACKAGE_BLOCK_NAME],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "package-block end failed (may already be ended): %s", result.stderr
        )

    if not _remove_total_block_hosts():
        logger.warning("Failed to remove total-block hosts entries")
    if not _remove_total_block_iptables():
        logger.warning("Failed to remove total-block iptables rules")

    flush_dns_cache()
    logger.info("Total gaming block ended - normal enforcement resumes.")
