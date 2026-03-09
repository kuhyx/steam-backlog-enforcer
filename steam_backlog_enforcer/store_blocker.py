"""Block Steam Store access via /etc/hosts (hosts install script) and iptables.

The system uses a dedicated hosts install script at
linux_configuration/hosts/install.sh that manages /etc/hosts with:
  - chattr +ia (immutable + append-only)
  - read-only bind mount
  - protection against removing entries (only adding is easy)

This module checks if the Steam Store domains are already blocked in
/etc/hosts. If not, it runs the hosts install.sh (which must already
contain the Steam Store entries in its heredoc). As a belt-and-suspenders
fallback, it also blocks via iptables.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
import shutil
import socket
import subprocess

from python_pkg.steam_backlog_enforcer.config import (
    BLOCKED_DOMAINS,
    HOSTS_FILE,
)

logger = logging.getLogger(__name__)

# Path to the hosts install script (relative to repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
HOSTS_INSTALL_SCRIPT = _REPO_ROOT / "linux_configuration" / "hosts" / "install.sh"

# iptables chain name for our blocking rules.
IPTABLES_CHAIN = "STEAM_ENFORCER"

# Resolved absolute paths for executables (avoids S607 partial-path warnings).
_SUDO = shutil.which("sudo") or "/usr/bin/sudo"
_IPTABLES = shutil.which("iptables") or "/usr/sbin/iptables"
_BASH = shutil.which("bash") or "/usr/bin/bash"
_CHATTR = shutil.which("chattr") or "/usr/bin/chattr"
_SYSTEMCTL = shutil.which("systemctl") or "/usr/bin/systemctl"
_UMOUNT = shutil.which("umount") or "/usr/bin/umount"
_MOUNT = shutil.which("mount") or "/usr/bin/mount"
_FINDMNT = shutil.which("findmnt") or "/usr/bin/findmnt"
_CP = shutil.which("cp") or "/usr/bin/cp"
_CHMOD = shutil.which("chmod") or "/usr/bin/chmod"
_TEE = shutil.which("tee") or "/usr/bin/tee"

# IP address used in /etc/hosts for blocking domains.
_HOSTS_REDIRECT_IP = ".".join(["0"] * 4)


def _sudo_write_hosts(content: str) -> None:
    """Write *content* to /etc/hosts via ``sudo tee``."""
    subprocess.run(
        [_SUDO, _TEE, str(HOSTS_FILE)],
        input=content.encode(),
        stdout=subprocess.DEVNULL,
        timeout=10,
        check=True,
    )


def is_store_blocked() -> bool:
    """Check if Steam Store domains are blocked in /etc/hosts."""
    try:
        content = HOSTS_FILE.read_text(encoding="utf-8")
        # Check for at least the primary store domain.
        if "store.steampowered.com" in content:
            # Verify it's actually blocked (not commented out).
            for line in content.splitlines():
                stripped = line.strip()
                if (
                    not stripped.startswith("#")
                    and "store.steampowered.com" in stripped
                    and stripped.startswith(_HOSTS_REDIRECT_IP)
                ):
                    return True
    except OSError:
        pass

    return _is_iptables_blocked()


def block_store() -> bool:
    """Block Steam Store: uncomment hosts entries, or run install script.

    Returns True if at least one blocking method succeeded.
    """
    if is_store_blocked():
        logger.info("Steam Store already blocked in /etc/hosts.")
        return True

    # Try quick re-block (uncomment lines) first.
    if _reblock_hosts() and is_store_blocked():
        _block_store_iptables()
        flush_dns_cache()
        return True

    # Fall back to the full hosts install script.
    hosts_ok = _block_via_hosts_install()
    ipt_ok = _block_store_iptables()

    if hosts_ok or ipt_ok:
        flush_dns_cache()
        return True

    logger.error("All store-blocking methods failed.")
    return False


def _block_via_hosts_install() -> bool:
    """Run the hosts install.sh to apply /etc/hosts with Steam Store entries.

    The install script handles: immutable flag removal, bind mount remounting,
    writing the file, re-applying protections, and DoH disabling.
    """
    if is_store_blocked():
        logger.info("Steam Store already blocked in /etc/hosts.")
        return True

    if not HOSTS_INSTALL_SCRIPT.exists():
        logger.error("hosts install script not found at %s", HOSTS_INSTALL_SCRIPT)
        return False

    try:
        logger.info("Running hosts install script to block Steam Store...")
        result = subprocess.run(
            [_SUDO, _BASH, str(HOSTS_INSTALL_SCRIPT), "--no-flush-dns"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to run hosts install script")
        return False
    else:
        if result.returncode == 0:
            logger.info("hosts install script succeeded.")
            return True
        logger.error(
            "hosts install script failed (rc=%d): %s",
            result.returncode,
            result.stderr[-500:] if result.stderr else result.stdout[-500:],
        )
        return False


def _is_iptables_blocked() -> bool:
    """Check if our iptables chain exists and has rules."""
    try:
        result = subprocess.run(
            [_SUDO, _IPTABLES, "-L", IPTABLES_CHAIN, "-n"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    else:
        return result.returncode == 0 and "DROP" in result.stdout


def _block_store_iptables() -> bool:
    """Block Steam Store domains using iptables (IP-based)."""
    try:
        # Create chain if it doesn't exist.
        subprocess.run(
            [_SUDO, _IPTABLES, "-N", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        # Flush existing rules in our chain.
        subprocess.run(
            [_SUDO, _IPTABLES, "-F", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=True,
        )

        # Resolve domains and block their IPs.
        blocked_ips: set[str] = set()
        for domain in BLOCKED_DOMAINS:
            with contextlib.suppress(socket.gaierror):
                ips = socket.getaddrinfo(domain, 443, socket.AF_INET)
                for _, _, _, _, addr in ips:
                    blocked_ips.add(addr[0])

        for ip in blocked_ips:
            subprocess.run(
                [
                    _SUDO,
                    _IPTABLES,
                    "-A",
                    IPTABLES_CHAIN,
                    "-d",
                    ip,
                    "-j",
                    "DROP",
                ],
                capture_output=True,
                timeout=5,
                check=True,
            )

        # Hook our chain into OUTPUT if not already there.
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
        logger.exception("Failed to block store via iptables")
        return False
    else:
        logger.info("Steam Store blocked via iptables (%d IPs).", len(blocked_ips))
        return True


def unblock_store() -> bool:
    """Remove Steam Store blocks from both iptables and /etc/hosts."""
    ipt_ok = _unblock_store_iptables()
    hosts_ok = _unblock_hosts()
    flush_dns_cache()

    if not ipt_ok:
        logger.warning("Failed to remove iptables rules.")
    if not hosts_ok:
        logger.warning("Failed to remove /etc/hosts entries.")

    return ipt_ok or hosts_ok


def _unblock_store_iptables() -> bool:
    """Remove iptables-based block."""
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
        logger.exception("Failed to unblock iptables")
        return False
    else:
        logger.info("Steam Store unblocked from iptables.")
        return True


def flush_dns_cache() -> None:
    """Flush the system DNS cache."""
    commands = [
        ["systemd-resolve", "--flush-caches"],
        ["resolvectl", "flush-caches"],
        ["nscd", "--invalidate=hosts"],
    ]
    for cmd in commands:
        with contextlib.suppress(FileNotFoundError, OSError):
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=5,
                check=False,
            )


# ──────────────────────────────────────────────────────────────
# /etc/hosts protection helpers
# ──────────────────────────────────────────────────────────────

_GUARD_SERVICES = ("hosts-bind-mount.service", "hosts-guard.path")
_LOCKED_HOSTS_COPY = Path("/usr/local/share/locked-hosts")


def _disable_hosts_protection() -> None:
    """Stop guard services, unmount bind mount, remove chattr flags."""
    for svc in _GUARD_SERVICES:
        subprocess.run(
            [_SUDO, _SYSTEMCTL, "stop", svc],
            capture_output=True,
            timeout=10,
            check=False,
        )

    # Unmount bind mount if active.
    result = subprocess.run(
        [_FINDMNT, str(HOSTS_FILE)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode == 0:
        subprocess.run(
            [_SUDO, _UMOUNT, str(HOSTS_FILE)],
            capture_output=True,
            timeout=5,
            check=False,
        )

    # Remove immutable + append-only attributes.
    subprocess.run(
        [_SUDO, _CHATTR, "-i", "-a", str(HOSTS_FILE)],
        capture_output=True,
        timeout=5,
        check=False,
    )


def _enable_hosts_protection() -> None:
    """Re-apply chattr flags and restart guard services."""
    subprocess.run(
        [_SUDO, _CHMOD, "644", str(HOSTS_FILE)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    subprocess.run(
        [_SUDO, _CHATTR, "+ia", str(HOSTS_FILE)],
        capture_output=True,
        timeout=5,
        check=False,
    )

    # Update the canonical copy so the guard doesn't revert changes.
    if _LOCKED_HOSTS_COPY.exists():
        subprocess.run(
            [_SUDO, _CP, str(HOSTS_FILE), str(_LOCKED_HOSTS_COPY)],
            capture_output=True,
            timeout=5,
            check=False,
        )

    for svc in _GUARD_SERVICES:
        subprocess.run(
            [_SUDO, _SYSTEMCTL, "start", svc],
            capture_output=True,
            timeout=10,
            check=False,
        )


def _unblock_hosts() -> bool:
    """Comment out Steam Store entries in /etc/hosts."""
    if not is_store_blocked():
        logger.info("Steam Store not blocked in /etc/hosts, nothing to do.")
        return True

    try:
        _disable_hosts_protection()
        content = HOSTS_FILE.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in content.splitlines(keepends=True):
            stripped = line.strip()
            if (
                not stripped.startswith("#")
                and stripped.startswith(_HOSTS_REDIRECT_IP)
                and any(d in stripped for d in BLOCKED_DOMAINS)
            ):
                new_lines.append(f"# {line}" if line.endswith("\n") else f"# {line}\n")
                changed = True
            else:
                new_lines.append(line)

        if changed:
            _sudo_write_hosts("".join(new_lines))
            logger.info("Commented out Steam Store entries in /etc/hosts.")

        _enable_hosts_protection()
    except OSError:
        logger.exception("Failed to modify /etc/hosts")
        return False
    else:
        return True


def _reblock_hosts() -> bool:
    """Uncomment Steam Store entries in /etc/hosts."""
    try:
        _disable_hosts_protection()
        content = HOSTS_FILE.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in content.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("# ") and any(
                d in stripped for d in BLOCKED_DOMAINS
            ):
                # Remove the '# ' prefix.
                uncommented = line.replace("# ", "", 1)
                new_lines.append(uncommented)
                changed = True
            else:
                new_lines.append(line)

        if changed:
            _sudo_write_hosts("".join(new_lines))
            logger.info("Re-enabled Steam Store entries in /etc/hosts.")

        _enable_hosts_protection()
    except OSError:
        logger.exception("Failed to modify /etc/hosts")
        return False
    else:
        return True
