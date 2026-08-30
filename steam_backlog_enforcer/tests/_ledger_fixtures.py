"""Shared builders for the LeetCode ledger tests.

Split out of ``test_leetcode_ledger.py`` to keep every file inside the 250-line
cap. The ``key_file`` fixture is imported by name into each test module, which
is what registers it there.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

LEDGER_PKG = "steam_backlog_enforcer._leetcode_ledger"
KEY = b"0123456789abcdef0123456789abcdef"


def sign(entry: dict[str, Any], key: bytes = KEY) -> dict[str, Any]:
    """Attach a genuine signature to an entry.

    Args:
        entry: The entry to sign.
        key: The signing key.

    Returns:
        The same entry with an ``hmac`` field.
    """
    payload = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    entry["hmac"] = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return entry


def credit(*, when: datetime, entry_id: str = "ac:1") -> dict[str, Any]:
    """Build a signed credit entry submitted at *when*.

    Args:
        when: The submission time.
        entry_id: The entry id, unique per credit.

    Returns:
        A signed credit entry.
    """
    return sign(
        {
            "entry_id": entry_id,
            "kind": "credit",
            "day": when.date().isoformat(),
            "created_at": when.isoformat(),
            "amount": 1,
            "device": "pc",
            "detail": {
                "source": "leetcode",
                "submitted_at": str(int(when.timestamp())),
            },
        }
    )


def write_ledger(path: Path, entries: list[dict[str, Any]]) -> Path:
    """Write a ledger file.

    Args:
        path: Directory to write into.
        entries: The entries to store.

    Returns:
        The ledger path.
    """
    ledger = path / "ledger.json"
    ledger.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    return ledger


@pytest.fixture
def key_file(tmp_path: Path) -> Iterator[Path]:
    """Point the module at a throwaway signing key.

    Args:
        tmp_path: pytest's temporary directory.

    Yields:
        The key path, with the module patched to use it.
    """
    path = tmp_path / "hmac.key"
    path.write_bytes(KEY)
    with patch(f"{LEDGER_PKG}.HMAC_KEY_FILE", path):
        yield path
