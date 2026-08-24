"""Steam-store blocking at the iptables/DNS layer.

These call nothing else in the blocker, so they extract cleanly: the
one-way dependency is what keeps store_blocker importable.
Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
import shutil
import socket
import subprocess

from steam_backlog_enforcer.config import (
    BLOCKED_DOMAINS,
)

logger = logging.getLogger(__name__)

# Path to the hosts install script. _REPO_ROOT resolves to $HOME (this
# module lives two levels below it); the script itself is in the
# linux_configuration checkout under testsAndMisc, not directly under $HOME.
_REPO_ROOT = Path(__file__).resolve().parents[2]
HOSTS_INSTALL_SCRIPT = (
    _REPO_ROOT
    / "testsAndMisc"
    / "linux_configuration"
    / "scripts"
    / "periodic_background"
    / "hosts"
    / "install.sh"
)

# iptables chain name for our blocking rules.
IPTABLES_CHAIN = "STEAM_ENFORCER"

# Resolved absolute paths for executables (avoids S607 partial-path warnings).
_SUDO = shutil.which("sudo") or "/usr/bin/sudo"
_IPTABLES = shutil.which("iptables") or "/usr/sbin/iptables"
_BASH = shutil.which("bash") or "/usr/bin/bash"
_GUARDCTL = shutil.which("guardctl") or "/usr/local/bin/guardctl"
_TEE = shutil.which("tee") or "/usr/bin/tee"

# IP address used in /etc/hosts for blocking domains.
_HOSTS_REDIRECT_IP = ".".join(["0"] * 4)


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
