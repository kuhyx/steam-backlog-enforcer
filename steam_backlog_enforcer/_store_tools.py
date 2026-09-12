"""The executables and paths every store-blocking layer shells out to.

One copy, imported by the hosts, iptables and orchestration modules alike --
each used to carry its own after the 250-line split, three blocks that had
to be kept identical by hand.
"""

from __future__ import annotations

from pathlib import Path
import shutil

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
SUDO = shutil.which("sudo") or "/usr/bin/sudo"
IPTABLES = shutil.which("iptables") or "/usr/sbin/iptables"
BASH = shutil.which("bash") or "/usr/bin/bash"
GUARDCTL = shutil.which("guardctl") or "/usr/local/bin/guardctl"
TEE = shutil.which("tee") or "/usr/bin/tee"

# IP address used in /etc/hosts for blocking domains.
HOSTS_REDIRECT_IP = ".".join(["0"] * 4)
