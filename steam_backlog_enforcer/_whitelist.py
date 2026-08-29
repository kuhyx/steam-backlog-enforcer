"""Whitelist hardening: time-locked exceptions, reason validation, immutability."""

from __future__ import annotations

from collections import Counter
import importlib
import logging
import math
import re
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer.config import CONFIG_DIR

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

# From <linux/fs.h>. FS_IOC_GETFLAGS is the 64-bit encoding of _IOR('f', 1,
# long); FS_IMMUTABLE_FL is the "immutable" bit that `chattr +i` sets.
_FS_IOC_GETFLAGS = 0x80086601
_FS_IMMUTABLE_FL = 0x00000010

_MOVED_TO_WHITELIST_LOCKING = frozenset(
    {
        "_append_audit_log",
        "_immutable_flag_is",
        "_load_approved",
        "_save_approved",
        "_try_set_immutable",
        "add_pending_exception",
        "get_approved_exception_ids",
        "lock_enforcement_files",
        "unlock_for_write",
    }
)


# Whatever the re-exported name turns out to be -- a function, a class or
# a constant. Aliased so the annotation is a name rather than a bare Any.
type _Reexport = Any


def __getattr__(name: str) -> _Reexport:
    """Re-export the names that moved to :mod:`_whitelist_locking`.

    Deferred rather than imported at the top because _whitelist_locking imports
    back from this module, so a module-level import would be circular.
    """
    if name in _MOVED_TO_WHITELIST_LOCKING:
        module = importlib.import_module("steam_backlog_enforcer._whitelist_locking")
        return getattr(module, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
