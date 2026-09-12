"""Toggling the protected/immutable flag on /etc/hosts around edits.

Leaf helpers: they call nothing else in the blocker, so extracting them
introduces no cycle. Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from steam_backlog_enforcer._store_tools import (
    GUARDCTL,
    SUDO,
    TEE,
)
from steam_backlog_enforcer.config import (
    BLOCKED_DOMAINS,
    HOSTS_FILE,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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


def rewrite_hosts_lines(
    rewrite: Callable[[str], str | None], done_message: str
) -> bool:
    """Apply ``rewrite`` to every /etc/hosts line, under the protection dance.

    ``rewrite`` returns the replacement for a line, or ``None`` to keep it.
    The file is only written -- and ``done_message`` only logged -- when a
    line actually changed; protection is lifted before and restored after
    either way.

    Returns:
        Whether the edit (or the no-op) completed without an OSError.
    """
    try:
        _disable_hosts_protection()
        content = HOSTS_FILE.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in content.splitlines(keepends=True):
            replacement = rewrite(line)
            if replacement is None:
                new_lines.append(line)
            else:
                new_lines.append(replacement)
                changed = True

        if changed:
            _sudo_write_hosts("".join(new_lines))
            logger.info(done_message)

        _enable_hosts_protection()
    except OSError:
        logger.exception("Failed to modify /etc/hosts")
        return False
    return True


def _uncomment_blocked(line: str) -> str | None:
    """The line with its '# ' prefix removed, if it is a commented-out block."""
    stripped = line.strip()
    if stripped.startswith("# ") and any(d in stripped for d in BLOCKED_DOMAINS):
        return line.replace("# ", "", 1)
    return None


def _reblock_hosts() -> bool:
    """Uncomment Steam Store entries in /etc/hosts."""
    return rewrite_hosts_lines(
        _uncomment_blocked, "Re-enabled Steam Store entries in /etc/hosts."
    )
