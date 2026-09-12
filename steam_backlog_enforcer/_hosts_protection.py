"""Toggling the protected/immutable flag on /etc/hosts around edits.

Leaf helpers: they call nothing else in the blocker, so extracting them
introduces no cycle. Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

import logging
import subprocess

from steam_backlog_enforcer._store_tools import (
    GUARDCTL,
    SUDO,
    TEE,
)
from steam_backlog_enforcer.config import (
    BLOCKED_DOMAINS,
    HOSTS_FILE,
)

logger = logging.getLogger(__name__)


def _disable_hosts_protection() -> None:
    """Temporarily unlock /etc/hosts so its content can be edited.

    Guard-lib: stop watcher, collapse bind mount, chattr -i.
    """
    subprocess.run(
        [SUDO, GUARDCTL, "file-guard", "pacman-unlock", "hosts"],
        capture_output=True,
        timeout=10,
        check=False,
    )


def _enable_hosts_protection() -> None:
    """Re-lock /etc/hosts, adopting its current content as the new canonical.

    Guard-lib: chattr +i, reapply bind mount, restart watcher.
    """
    subprocess.run(
        [SUDO, GUARDCTL, "file-guard", "sync", "hosts"],
        capture_output=True,
        timeout=10,
        check=False,
    )


def _sudo_write_hosts(content: str) -> None:
    """Write *content* to /etc/hosts via ``sudo tee``."""
    subprocess.run(
        [SUDO, TEE, str(HOSTS_FILE)],
        input=content.encode(),
        stdout=subprocess.DEVNULL,
        timeout=10,
        check=True,
    )


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
    return True
