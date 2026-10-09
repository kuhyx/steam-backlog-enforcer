"""Tests for stat-stamp invalidation of the earner answer cache.

A credited workout (or LeetCode / reading credit) rewrites a file the answer
is derived from. The stamp makes the very next tick re-ask instead of serving
the memoised pre-credit answer for the rest of the 60 s TTL.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _status_api, _workout_budget
from steam_backlog_enforcer._status_api import AnswerCache, file_stamp

# Bound at import, before conftest swaps the module attribute for a tmp path.
from steam_backlog_enforcer._workout_budget import workout_log_path
from steam_backlog_enforcer.config import Config

_API = "steam_backlog_enforcer._status_api"
_URL = "http://127.0.0.1:8770/api/status"


def _unstatable(error: OSError) -> MagicMock:
    """A path whose ``stat`` fails with ``error`` (hashable, like a Path)."""
    path = MagicMock(spec=Path)
    path.stat.side_effect = error
    return path


class TestFileStamp:
    """Identity of a file's contents, or None."""

    def test_missing_file_is_none(self, tmp_path: Path) -> None:
        assert file_stamp(tmp_path / "absent.json") is None

    def test_same_contents_same_stamp(self, tmp_path: Path) -> None:
        path = tmp_path / "log.json"
        path.write_text("{}")
        assert file_stamp(path) == file_stamp(path)

    def test_atomic_replace_changes_the_stamp(self, tmp_path: Path) -> None:
        path = tmp_path / "log.json"
        path.write_text("{}")
        before = file_stamp(path)
        tmp = tmp_path / "log.json.tmp"
        tmp.write_text("{}")
        tmp.replace(path)
        # Same size and possibly the same mtime tick: the inode tells them apart.
        assert file_stamp(path) != before

    def test_in_place_growth_changes_the_stamp(self, tmp_path: Path) -> None:
        path = tmp_path / "log.json"
        path.write_text("{}")
        before = file_stamp(path)
        path.write_text('{"a": 1}')
        assert file_stamp(path) != before

    def test_stat_error_warns_once_per_distinct_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _unstatable(PermissionError("denied"))
        with caplog.at_level(logging.WARNING, logger=_API):
            assert file_stamp(path) is None
            assert file_stamp(path) is None
            path.stat.side_effect = PermissionError("still denied")
            assert file_stamp(path) is None
        warnings = [r for r in caplog.records if "Cannot stat" in r.getMessage()]
        assert len(warnings) == 2
        assert "60s TTL" in warnings[0].getMessage()
        _status_api._stat_errors.pop(path, None)

    def test_recovery_re_arms_the_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "log.json"
        path.write_text("{}")
        with caplog.at_level(logging.WARNING, logger=_API):
            with patch.object(Path, "stat", side_effect=PermissionError("x")):
                assert file_stamp(path) is None
            assert file_stamp(path) is not None
            assert path not in _status_api._stat_errors
            with patch.object(Path, "stat", side_effect=PermissionError("x")):
                assert file_stamp(path) is None
        assert caplog.text.count("Cannot stat") == 2
        _status_api._stat_errors.pop(path, None)

    def test_vanishing_clears_a_recorded_error(self, tmp_path: Path) -> None:
        path = tmp_path / "log.json"
        _status_api._stat_errors[path] = "old"
        assert file_stamp(path) is None
        assert path not in _status_api._stat_errors


class TestAnswerCacheStamp:
    """A stored stamp must match the caller's for the answer to be reused."""

    def test_matching_stamp_hits(self) -> None:
        cache = AnswerCache()
        cache.store(_URL, answer=True, stamp=(1, 2, 3))
        assert cache.fresh(_URL, stamp=(1, 2, 3)) is True

    def test_changed_stamp_misses(self) -> None:
        cache = AnswerCache()
        cache.store(_URL, answer=False, stamp=(1, 2, 3))
        assert cache.fresh(_URL, stamp=(1, 2, 4)) is None

    def test_file_appearing_misses(self) -> None:
        cache = AnswerCache()
        cache.store(_URL, answer=False, stamp=None)
        assert cache.fresh(_URL, stamp=(1, 2, 3)) is None

    def test_unstamped_callers_still_hit(self) -> None:
        cache = AnswerCache()
        cache.store(_URL, answer=True)
        assert cache.fresh(_URL) is True

    def test_entries_carry_the_stamp(self) -> None:
        cache = AnswerCache()
        cache.store(_URL, answer=True, stamp=(9, 9, 9))
        _when, answer, stamp = cache._entries[_URL]
        assert (answer, stamp) == (True, (9, 9, 9))

    def test_ttl_still_applies_with_a_matching_stamp(self) -> None:
        cache = AnswerCache()
        with patch(f"{_API}.time.monotonic", return_value=0.0):
            cache.store(_URL, answer=True, stamp=(1, 2, 3))
        with patch(f"{_API}.time.monotonic", return_value=61.0):
            assert cache.fresh(_URL, stamp=(1, 2, 3)) is None


class TestWorkoutLogPath:
    """Where screen-locker's log.json is read from."""

    def test_expands_the_home_directory(self) -> None:
        config = Config()
        config.workout_log_path = "~/locker/log.json"
        assert workout_log_path(config) == Path.home() / "locker" / "log.json"

    def test_default_points_at_screen_locker(self) -> None:
        expected = Path.home() / "src/screen-locker/screen_locker/log.json"
        assert workout_log_path(Config()) == expected


class TestWorkoutAnswerFollowsTheLog:
    """A rewritten log.json re-asks the locker inside the TTL."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        _workout_budget.reset_cache()

    def test_credit_is_seen_on_the_next_call(self) -> None:
        config = Config()
        # conftest redirected this to a tmp path; that is the file we rewrite.
        log = _workout_budget.workout_log_path(config)
        log.parent.mkdir(parents=True)
        log.write_text("[]")
        with patch(
            f"{_workout_budget.__name__}._fetch_workout_today",
            side_effect=[False, True],
        ) as fetch:
            assert _workout_budget.workout_logged_today(config) is False
            assert _workout_budget.workout_logged_today(config) is False
            assert fetch.call_count == 1
            tmp = log.with_name("log.json.tmp")
            tmp.write_text('[{"credited": true}]')
            tmp.replace(log)
            assert _workout_budget.workout_logged_today(config) is True
        assert fetch.call_count == 2
