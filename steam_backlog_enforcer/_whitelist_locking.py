"""Making enforcement files immutable so they cannot be edited mid-block.

Split out of :mod:`steam_backlog_enforcer._whitelist` to keep both files
under the 250-line cap.
"""

from __future__ import annotations

import array
import contextlib
import fcntl
import json
import logging
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, cast

from steam_backlog_enforcer._whitelist import (
    _FS_IMMUTABLE_FL,
    _FS_IOC_GETFLAGS,
    validate_reason,
)
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# File paths (patched in tests via conftest)
# ──────────────────────────────────────────────────────────────

APPROVED_EXCEPTIONS_FILE: Path = CONFIG_DIR / "approved_exceptions.json"
EXCEPTION_AUDIT_LOG: Path = CONFIG_DIR / "exception_audit.log"

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

_MIN_REASON_WORDS: int = 5
_MIN_REASON_LENGTH: int = 25
_MIN_ENTROPY: float = 3.0
# Reject runs of the same character longer than this (e.g. "aaaa").
_MAX_CHAR_RUN: int = 3


# ──────────────────────────────────────────────────────────────
# Reason validation
# ──────────────────────────────────────────────────────────────


def _immutable_flag_is(path: Path, *, immutable: bool) -> bool:
    """Report whether *path*'s immutable bit already equals *immutable*.

    Reading the flag is an ioctl, which costs no process; ``chattr`` costs a
    fork and an exec. Since ``lock_enforcement_files`` runs on every
    enforce-loop iteration, asking first turns a steady ~0.65 execs/second
    into none at all for a flag that essentially never changes.

    Fails closed: any uncertainty at all — filesystem without flag support,
    ioctl refused, file unreadable — reports False so the caller still shells
    out to chattr. A wrong True would silently stop enforcing immutability.

    Args:
        path: File to inspect.
        immutable: The state to compare against.

    Returns:
        True only if the flag could be read and already matches.
    """
    buf = array.array("L", [0])
    try:
        with path.open("rb") as handle:
            # mutate_flag defaults to True, so buf receives the flags in place.
            fcntl.ioctl(handle.fileno(), _FS_IOC_GETFLAGS, buf)
    except OSError, ValueError:
        return False
    return bool(buf[0] & _FS_IMMUTABLE_FL) is immutable


def _try_set_immutable(path: Path, *, immutable: bool) -> None:
    """Silently attempt to set or clear the immutable flag on *path*.

    This is a best-effort operation — it fails silently if chattr is not
    available, the process lacks the required capability, or the filesystem
    does not support the flag. When the flag already holds the requested
    value, no subprocess is spawned at all.

    Args:
        path: File to modify.
        immutable: True to set +i, False to clear -i.
    """
    if not path.exists():
        return
    if _immutable_flag_is(path, immutable=immutable):
        return
    chattr = shutil.which("chattr")
    if chattr is None:
        return
    flag = "+i" if immutable else "-i"
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            [chattr, flag, str(path)],
            capture_output=True,
            check=False,
            timeout=5,
        )


def lock_enforcement_files(config_file: Path) -> None:
    """Apply chattr +i to enforcement-critical config files.

    Called at the end of each enforce-loop iteration.  Requires that the
    daemon is running as root (or has CAP_LINUX_IMMUTABLE).

    Args:
        config_file: Path to the main config.json.
    """
    _try_set_immutable(config_file, immutable=True)
    _try_set_immutable(APPROVED_EXCEPTIONS_FILE, immutable=True)


def unlock_for_write(path: Path) -> None:
    """Clear the immutable flag before writing *path*.

    Args:
        path: File to unlock.
    """
    _try_set_immutable(path, immutable=False)


# ──────────────────────────────────────────────────────────────
# Persistence helpers
# ──────────────────────────────────────────────────────────────


def _load_approved() -> list[dict[str, object]]:
    """Load approved exception entries from disk."""
    if not APPROVED_EXCEPTIONS_FILE.exists():
        return []
    try:
        data: object = json.loads(APPROVED_EXCEPTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return cast("list[dict[str, object]]", data)
    except json.JSONDecodeError, OSError, ValueError:
        pass
    return []


def _save_approved(entries: list[dict[str, object]]) -> None:
    """Persist approved exception entries to disk."""
    unlock_for_write(APPROVED_EXCEPTIONS_FILE)
    _atomic_write(APPROVED_EXCEPTIONS_FILE, json.dumps(entries, indent=2) + "\n")
    _try_set_immutable(APPROVED_EXCEPTIONS_FILE, immutable=True)


def _append_audit_log(app_id: int, reason: str, event: str) -> None:
    """Append one line to the append-only audit log.

    Each line has the format::

        ISO-TIMESTAMP | EVENT | app_id=NNN | reason='...'

    Args:
        app_id: Steam application ID involved.
        reason: Justification text supplied by the user.
        event: Short event label such as ``REQUESTED`` or ``APPROVED``.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{timestamp} | {event} | app_id={app_id} | reason={reason!r}\n"
    EXCEPTION_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EXCEPTION_AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────


def add_pending_exception(app_id: int, reason: str) -> str:
    """Add a whitelist exception for *app_id* immediately.

    The entry becomes active right away (no cooldown).  Returns a
    human-readable status message.

    Args:
        app_id: Steam application ID to add.
        reason: Validated justification text (must pass :func:`validate_reason`).

    Returns:
        Human-readable confirmation message.

    Raises:
        ValueError: If the reason fails validation or the ID is already approved.
    """
    err = validate_reason(reason)
    if err is not None:
        raise ValueError(err)

    approved = _load_approved()
    if any(int(e["app_id"]) == app_id for e in approved):
        msg = f"AppID {app_id} is already in the approved exceptions list."
        raise ValueError(msg)

    now = time.time()
    approved.append(
        {
            "app_id": app_id,
            "reason": reason,
            "approved_at": now,
        }
    )
    _save_approved(approved)
    _append_audit_log(app_id, reason, "APPROVED")

    return f"Exception approved for AppID {app_id}. Active immediately. Reason logged."


def get_approved_exception_ids() -> frozenset[int]:
    """Return the frozenset of currently approved exception app IDs.

    Returns:
        Frozenset of approved app IDs.
    """
    approved = _load_approved()
    return frozenset(int(e["app_id"]) for e in approved)
