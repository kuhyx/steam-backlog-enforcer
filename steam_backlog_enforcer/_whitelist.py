"""Whitelist hardening: time-locked exceptions, reason validation, immutability."""

from __future__ import annotations

from collections import Counter
import contextlib
import json
import logging
import math
import re
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, cast

from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# File paths (patched in tests via conftest)
# ──────────────────────────────────────────────────────────────

PENDING_EXCEPTIONS_FILE: Path = CONFIG_DIR / "pending_exceptions.json"
APPROVED_EXCEPTIONS_FILE: Path = CONFIG_DIR / "approved_exceptions.json"
EXCEPTION_AUDIT_LOG: Path = CONFIG_DIR / "exception_audit.log"

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

WHITELIST_COOLDOWN_SECONDS: int = 86400  # 24 hours

_MIN_REASON_WORDS: int = 5
_MIN_REASON_LENGTH: int = 25
_MIN_ENTROPY: float = 3.0
# Reject runs of the same character longer than this (e.g. "aaaa").
_MAX_CHAR_RUN: int = 3


# ──────────────────────────────────────────────────────────────
# Reason validation
# ──────────────────────────────────────────────────────────────


def _shannon_entropy(text: str) -> float:
    """Return Shannon entropy (bits per character) for *text*.

    Whitespace is excluded before counting so spaces don't inflate entropy.

    Args:
        text: Input string to measure.

    Returns:
        Entropy in bits per character, or 0.0 for empty input.
    """
    chars = [c.lower() for c in text if not c.isspace()]
    if not chars:
        return 0.0
    total = len(chars)
    counts = Counter(chars)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def validate_reason(reason: str) -> str | None:
    """Validate that a whitelist exception reason is genuine.

    Returns None when the reason is acceptable, or a human-readable error
    string that explains why it was rejected.

    Args:
        reason: User-supplied justification text.

    Returns:
        None if valid, or an error message string if invalid.
    """
    stripped = reason.strip()

    if len(stripped) < _MIN_REASON_LENGTH:
        return (
            f"Reason is too short ({len(stripped)} chars; "
            f"need at least {_MIN_REASON_LENGTH})."
        )

    words = stripped.split()
    if len(words) < _MIN_REASON_WORDS:
        return (
            f"Reason must contain at least {_MIN_REASON_WORDS} words "
            f"(got {len(words)})."
        )

    entropy = _shannon_entropy(stripped)
    if entropy < _MIN_ENTROPY:
        return (
            f"Reason appears to be random characters "
            f"(entropy {entropy:.2f} < {_MIN_ENTROPY}). "
            "Write a genuine justification."
        )

    # Reject runs of the same character: aaaa, bbbbbb, etc.
    if re.search(r"(.)\1{3,}", stripped, re.IGNORECASE):
        return "Reason contains repeated characters. Write a genuine justification."

    # Reject simple two-character alternating patterns: ababab, asasas, etc.
    if re.search(r"(..)(\1){3,}", stripped, re.IGNORECASE):
        return "Reason contains repetitive patterns. Write a genuine justification."

    return None


# ──────────────────────────────────────────────────────────────
# Immutability helpers
# ──────────────────────────────────────────────────────────────


def _try_set_immutable(path: Path, *, immutable: bool) -> None:
    """Silently attempt to set or clear the immutable flag on *path*.

    This is a best-effort operation — it fails silently if chattr is not
    available, the process lacks the required capability, or the filesystem
    does not support the flag.

    Args:
        path: File to modify.
        immutable: True to set +i, False to clear -i.
    """
    if not path.exists():
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


def _load_pending() -> list[dict[str, object]]:
    """Load pending exception entries from disk."""
    if not PENDING_EXCEPTIONS_FILE.exists():
        return []
    try:
        data: object = json.loads(PENDING_EXCEPTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return cast("list[dict[str, object]]", data)
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return []


def _save_pending(entries: list[dict[str, object]]) -> None:
    """Persist pending exception entries to disk."""
    _atomic_write(PENDING_EXCEPTIONS_FILE, json.dumps(entries, indent=2) + "\n")


def _load_approved() -> list[dict[str, object]]:
    """Load approved exception entries from disk."""
    if not APPROVED_EXCEPTIONS_FILE.exists():
        return []
    try:
        data: object = json.loads(APPROVED_EXCEPTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return cast("list[dict[str, object]]", data)
    except (json.JSONDecodeError, OSError, ValueError):
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
    """Request a new whitelist exception for *app_id*.

    The entry becomes active only after ``WHITELIST_COOLDOWN_SECONDS`` have
    elapsed (24 h by default).  Returns a human-readable status message.

    Args:
        app_id: Steam application ID to add.
        reason: Validated justification text (must pass :func:`validate_reason`).

    Returns:
        Human-readable confirmation or remaining-cooldown message.

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

    pending = _load_pending()
    for entry in pending:
        if int(entry["app_id"]) == app_id:
            elapsed = time.time() - float(entry["requested_at"])
            remaining = WHITELIST_COOLDOWN_SECONDS - elapsed
            if remaining > 0:
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                return (
                    f"AppID {app_id} is already pending; approves in {hours}h {mins}m."
                )
            # Cooldown already elapsed for this pending entry — promote now.
            break

    entry_new: dict[str, object] = {
        "app_id": app_id,
        "reason": reason,
        "requested_at": time.time(),
    }
    pending.append(entry_new)
    _save_pending(pending)
    _append_audit_log(app_id, reason, "REQUESTED")

    hours = WHITELIST_COOLDOWN_SECONDS // 3600
    return (
        f"Exception requested for AppID {app_id}. "
        f"Will become active in {hours}h. Reason logged."
    )


def promote_pending_exceptions() -> list[int]:
    """Move cooldown-elapsed pending entries to the approved list.

    Called by the enforce daemon on each loop iteration.  Returns the list
    of app IDs that were promoted this call.

    Returns:
        List of newly approved app IDs (may be empty).
    """
    pending = _load_pending()
    now = time.time()
    still_pending: list[dict[str, object]] = []
    newly_approved: list[int] = []

    for entry in pending:
        elapsed = now - float(entry["requested_at"])
        if elapsed >= WHITELIST_COOLDOWN_SECONDS:
            app_id = int(entry["app_id"])
            approved = _load_approved()
            if not any(int(e["app_id"]) == app_id for e in approved):
                approved.append(
                    {
                        "app_id": app_id,
                        "reason": entry["reason"],
                        "approved_at": now,
                    }
                )
                _save_approved(approved)
                _append_audit_log(app_id, str(entry["reason"]), "APPROVED")
                newly_approved.append(app_id)
        else:
            still_pending.append(entry)

    if len(still_pending) != len(pending):
        _save_pending(still_pending)

    return newly_approved


def get_approved_exception_ids() -> frozenset[int]:
    """Return the frozenset of currently approved exception app IDs.

    Does NOT trigger promotion — call :func:`promote_pending_exceptions`
    explicitly when timely promotion is required (e.g. the enforce loop).

    Returns:
        Frozenset of approved app IDs.
    """
    approved = _load_approved()
    return frozenset(int(e["app_id"]) for e in approved)


def list_pending_exceptions() -> list[dict[str, object]]:
    """Return a copy of the current pending exception list.

    Returns:
        List of pending exception dicts with keys app_id, reason, requested_at.
    """
    return list(_load_pending())
