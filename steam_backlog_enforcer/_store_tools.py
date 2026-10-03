"""The executables and paths every store-blocking layer shells out to.

One copy, imported by the hosts, iptables and orchestration modules alike --
each used to carry its own after the 250-line split, three blocks that had
to be kept identical by hand.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

# Path to the hosts install script. _SRC_ROOT is ~/src (this module lives two
# levels below it); the generator moved out of testsAndMisc into its own
# hosts-blocker repo, whose custom_entries.hosts carries the Steam Store block.
_SRC_ROOT = Path(__file__).resolve().parents[2]
HOSTS_INSTALL_SCRIPT = _SRC_ROOT / "hosts-blocker" / "install.sh"

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


def run_quiet(
    cmd: list[str], *, timeout: float = 5
) -> subprocess.CompletedProcess[bytes]:
    """Run ``cmd`` with output captured and no exception on a non-zero exit."""
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def ensure_chain_in_output(chain: str) -> None:
    """Hook ``chain`` into iptables' OUTPUT if it is not already there.

    Raises:
        subprocess.CalledProcessError: If the insert itself fails -- a chain
            that exists but is not reachable from OUTPUT blocks nothing.
    """
    probe = run_quiet([SUDO, IPTABLES, "-C", "OUTPUT", "-j", chain])
    if probe.returncode != 0:
        subprocess.run(
            [SUDO, IPTABLES, "-I", "OUTPUT", "-j", chain],
            capture_output=True,
            timeout=5,
            check=True,
        )
