"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._cmd_done import _backfill_polls_for_finished
from steam_backlog_enforcer.tests._polls_helpers import (
    CMD,
    TYPES,
    filling_fetch,
    hltb_cache_patched,
    poll_state,
    write_cache,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestBackfillPollsForFinished:
    """Tests for Backfill Polls For Finished."""

    def test_no_missing_returns_existing(self, tmp_path: Path) -> None:
        """Test no missing returns existing."""
        cache_file = write_cache(tmp_path, {"1": {"hours": 1.0, "polls": 5}})
        with (
            patch(f"{TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{CMD}.load_snapshot", return_value=[{"app_id": 1, "name": "G"}]),
        ):
            result = _backfill_polls_for_finished(poll_state([1]))
        assert result == {1: 5}

    def test_no_snapshot_no_missing(self) -> None:
        """Test no snapshot no missing."""
        with (
            patch(f"{CMD}.load_hltb_polls_cache", return_value={}),
            patch(f"{CMD}.load_snapshot", return_value=None),
        ):
            assert _backfill_polls_for_finished(poll_state([1])) == {}

    def test_missing_triggers_fetch(self, tmp_path: Path) -> None:
        """Test missing triggers fetch."""
        cache_file = write_cache(tmp_path, {"1": {"hours": 2.0, "polls": 0}})
        with (
            hltb_cache_patched(cache_file, tmp_path, filling_fetch(2.0, 9)),
            patch(f"{CMD}.load_snapshot", return_value=[{"app_id": 1, "name": "G"}]),
            patch(f"{CMD}._echo"),
        ):
            result = _backfill_polls_for_finished(poll_state([1]))
        assert result == {1: 9}

    def test_extra_app_id_with_zero_polls_added(self, tmp_path: Path) -> None:
        """Test extra app id with zero polls added."""
        cache_file = write_cache(tmp_path, {"7": {"hours": 1.0, "polls": 0}})
        with (
            hltb_cache_patched(cache_file, tmp_path, filling_fetch(1.0, 4)),
            patch(f"{CMD}.load_snapshot", return_value=[{"app_id": 7, "name": "G"}]),
            patch(f"{CMD}._echo"),
        ):
            result = _backfill_polls_for_finished(
                poll_state([], current=7), extra_app_id=7
            )
        assert result == {7: 4}

    def test_preserves_prior_hours_on_miss(self, tmp_path: Path) -> None:
        """Test preserves prior hours on miss."""
        cache_file = write_cache(tmp_path, {"3": {"hours": 4.0, "polls": 0}})
        # A clean miss: hours -1, polls 0.
        with (
            hltb_cache_patched(cache_file, tmp_path, filling_fetch(-1, 0)),
            patch(f"{CMD}.load_snapshot", return_value=[{"app_id": 3, "name": "G"}]),
            patch(f"{CMD}._echo"),
        ):
            _backfill_polls_for_finished(poll_state([3]))
        # Prior hours should be preserved on miss.
        final = json.loads(cache_file.read_text(encoding="utf-8"))
        assert final["3"]["hours"] == 4.0
