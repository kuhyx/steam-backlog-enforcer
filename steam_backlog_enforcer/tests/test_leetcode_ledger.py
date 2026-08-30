"""Tests for _leetcode_ledger: which entries count as a solve today.

The signature check is load-bearing. That module reproduces gatelock's
canonicalisation rather than importing it, because gatelock lives in the user's
site-packages and the enforcer runs as root. ``TestSignatureCanonicalisation``
pins it to a fixed vector so the duplication cannot drift silently -- if
leetcode-guard ever changes how it signs, that test fails instead of every
credit quietly ceasing to count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from steam_backlog_enforcer._leetcode_ledger import (
    _verified,
    read_ledger_solved_today,
)
from steam_backlog_enforcer.tests._ledger_fixtures import (
    KEY,
    credit,
    key_file,
    sign,
    write_ledger,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

__all__ = ["key_file"]


class TestSignatureCanonicalisation:
    """The duplicated eight lines must keep matching gatelock's."""

    def test_a_known_vector_still_verifies(self) -> None:
        """Pinned so a change in how entries are signed fails loudly here."""
        entry = {
            "entry_id": "ac:1",
            "kind": "credit",
            "day": "2026-08-30",
            "created_at": "2026-08-30T14:00:00+02:00",
            "amount": 1,
            "device": "pc",
            "detail": {
                "title_slug": "two-sum",
                "lang": "python3",
                "source": "leetcode",
                "submitted_at": "1788090000",
            },
            "hmac": "4f6986bdb019bf28f607918ffb1b5bc79d252f887ade2e25aa83a31d1e49423e",
        }
        assert _verified(entry, KEY) is True

    def test_a_tampered_entry_fails(self) -> None:
        """Changing any field must invalidate the signature."""
        entry = credit(when=datetime.now().astimezone())
        entry["amount"] = 99
        assert _verified(entry, KEY) is False

    def test_a_missing_signature_fails(self) -> None:
        """An entry with no hmac field is not a signed entry."""
        assert _verified({"kind": "credit"}, KEY) is False


class TestReadingTheLedger:
    """Which entries count, and which are ignored."""

    def test_a_credit_today_counts(self, tmp_path: Path, key_file: Path) -> None:
        """The ordinary case.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        ledger = write_ledger(tmp_path, [credit(when=datetime.now().astimezone())])
        assert read_ledger_solved_today(ledger) is True

    def test_a_credit_yesterday_does_not(self, tmp_path: Path, key_file: Path) -> None:
        """Yesterday's solve bought yesterday's hour, not today's.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        yesterday = datetime.now().astimezone() - timedelta(days=1)
        ledger = write_ledger(tmp_path, [credit(when=yesterday)])
        assert read_ledger_solved_today(ledger) is False

    def test_charges_and_seen_entries_do_not_count(
        self, tmp_path: Path, key_file: Path
    ) -> None:
        """A settled day is not a solved day, and seeding is worth nothing.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        rows = [
            sign(
                {
                    "entry_id": f"charge:{today}",
                    "kind": "charge",
                    "day": today,
                    "created_at": now.isoformat(),
                    "amount": 2,
                    "device": "pc",
                    "detail": {"source": "escape"},
                }
            ),
            sign(
                {
                    "entry_id": "ac:9",
                    "kind": "seen",
                    "day": today,
                    "created_at": now.isoformat(),
                    "amount": 0,
                    "device": "pc",
                    "detail": {"submitted_at": str(int(now.timestamp()))},
                }
            ),
        ]
        assert read_ledger_solved_today(write_ledger(tmp_path, rows)) is False

    def test_a_forged_credit_does_not_count(
        self, tmp_path: Path, key_file: Path
    ) -> None:
        """Appending JSON must not buy an hour.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        forged = credit(when=datetime.now().astimezone())
        forged["hmac"] = "00" * 32
        assert read_ledger_solved_today(write_ledger(tmp_path, [forged])) is False

    def test_a_missing_submitted_at_falls_back_to_the_day_key(
        self, tmp_path: Path, key_file: Path
    ) -> None:
        """Older credits predate the field and must still count.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
        """
        assert key_file.exists()
        now = datetime.now().astimezone()
        entry = sign(
            {
                "entry_id": "ac:2",
                "kind": "credit",
                "day": now.date().isoformat(),
                "created_at": now.isoformat(),
                "amount": 1,
                "device": "pc",
                "detail": {"source": "leetcode"},
            }
        )
        assert read_ledger_solved_today(write_ledger(tmp_path, [entry])) is True

    def test_an_unparsable_submitted_at_is_reported(
        self, tmp_path: Path, key_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt data falls back rather than crashing, and says so.

        Args:
            tmp_path: pytest's temporary directory.
            key_file: The patched signing key.
            caplog: pytest's log capture.
        """
        assert key_file.exists()
        now = datetime.now().astimezone()
        entry = credit(when=now, entry_id="ac:3")
        entry["detail"]["submitted_at"] = "not-a-number"
        entry = sign({k: v for k, v in entry.items() if k != "hmac"})
        assert read_ledger_solved_today(write_ledger(tmp_path, [entry])) is True
        assert "unparsable submitted_at" in caplog.text
