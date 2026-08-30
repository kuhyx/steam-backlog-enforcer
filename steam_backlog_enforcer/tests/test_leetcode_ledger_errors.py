"""Tests for _leetcode_ledger: every way of not getting an answer.

"Cannot check" is never "not solved". Each of these returns ``None``, which the
resolver must turn into no-bonus-plus-incident rather than into an honest
"nothing solved yet" -- the two are worth the same hour but not the same
notification.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._leetcode_ledger import (
    read_ledger_solved_today,
)
from steam_backlog_enforcer.tests._ledger_fixtures import (
    LEDGER_PKG,
    credit,
    key_file,
    write_ledger,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["key_file"]


class TestCannotCheck:
    """Every unreadable state is None, and None is never False."""

    def test_a_missing_ledger(self, tmp_path: Path, key_file: Path) -> None:
        """Deleting the ledger must not silently mean "nothing solved".

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        assert read_ledger_solved_today(tmp_path / "absent.json") is None

    def test_unparsable_json(self, tmp_path: Path, key_file: Path) -> None:
        """A truncated write is not an answer.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        broken = tmp_path / "ledger.json"
        broken.write_text("{ not json", encoding="utf-8")
        assert read_ledger_solved_today(broken) is None

    def test_no_entries_array(self, tmp_path: Path, key_file: Path) -> None:
        """A structurally wrong ledger is not an empty one.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        odd = tmp_path / "ledger.json"
        odd.write_text(json.dumps({"version": 1}), encoding="utf-8")
        assert read_ledger_solved_today(odd) is None

    def test_an_unreadable_key(self, tmp_path: Path) -> None:
        """Without the key nothing can be verified, so nothing can be trusted.

        Args:
            tmp_path: pytest's temporary directory.
        """
        ledger = write_ledger(tmp_path, [credit(when=datetime.now().astimezone())])
        with patch(f"{LEDGER_PKG}.HMAC_KEY_FILE", tmp_path / "absent.key"):
            assert read_ledger_solved_today(ledger) is None

    def test_an_empty_key(self, tmp_path: Path) -> None:
        """A truncated key file is as unusable as a missing one.

        Args:
            tmp_path: pytest's temporary directory.
        """
        empty = tmp_path / "hmac.key"
        empty.write_bytes(b"")
        ledger = write_ledger(tmp_path, [credit(when=datetime.now().astimezone())])
        with patch(f"{LEDGER_PKG}.HMAC_KEY_FILE", empty):
            assert read_ledger_solved_today(ledger) is None
