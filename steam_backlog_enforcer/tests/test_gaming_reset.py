"""Tests for ``_gaming_reset.reset_today``, the core shared by CLI and socket.

State, history and the budget audit log are the conftest-redirected tmp_path
files; the mount release is mocked (it would unmount the host's Steam).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from steam_backlog_enforcer import _gaming_reset, _playtime_log
from steam_backlog_enforcer._gaming_days import gaming_day_key
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    save_state,
)


def _today() -> str:
    return gaming_day_key(_gaming_reset.datetime.now(_gaming_reset.UTC).astimezone())


def _audit_records() -> list[dict[str, object]]:
    path = _playtime_log.budget_log_path(demo=False)
    return [json.loads(line) for line in path.read_text().splitlines()]


def _spent_state(day_key: str) -> PlaytimeState:
    return PlaytimeState(
        day_key=day_key,
        seconds=900.0,
        blocked_at=5.0,
        per_game={"1": 600.0, "2": 300.0},
        last_credited_key="1",
        warned_seconds=[600],
        budget_seconds=1800.0,
        carry={"2999-01-01": 120.0},
    )


class TestResetToday:
    """Zero the counter, release mounts, keep earned time, leave a record."""

    def test_zeroes_state_but_keeps_earned_time(self) -> None:
        save_state(_spent_state(_today()), demo=False)
        with patch.object(
            _gaming_reset, "release_block", return_value=[Path("/m/steam")]
        ):
            outcome = _gaming_reset.reset_today(source="ctl")
        assert outcome.day_key == _today()
        assert outcome.seconds_before == 900.0
        assert outcome.was_blocked is True
        assert outcome.released == [Path("/m/steam")]
        stored = load_state(demo=False)
        assert stored is not None
        assert (stored.seconds, stored.blocked_at, stored.per_game) == (0.0, 0.0, {})
        assert (stored.last_credited_key, stored.warned_seconds) == ("", [])
        assert (stored.budget_seconds, stored.carry) == (1800.0, {"2999-01-01": 120.0})
        assert stored.last_tick_at > 0

    def test_audit_record_has_the_before_picture(self) -> None:
        save_state(_spent_state(_today()), demo=False)
        with patch.object(_gaming_reset, "release_block", return_value=[Path("/m")]):
            _gaming_reset.reset_today(source="cli")
        record = _audit_records()[-1]
        assert record["kind"] == "gaming_reset"
        assert record["source"] == "cli"
        assert record["billed_seconds_before"] == 900.0
        assert record["billed_seconds_after"] == 0.0
        assert record["per_game_before"] == {"1": 600.0, "2": 300.0}
        assert record["released"] == ["/m"]

    def test_stale_day_is_rolled_over_first(self) -> None:
        save_state(_spent_state("2000-01-01"), demo=False)
        with patch.object(_gaming_reset, "release_block", return_value=[]):
            outcome = _gaming_reset.reset_today(source="ctl")
        assert outcome.seconds_before == 0.0
        assert outcome.was_blocked is False
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.day_key == _today()

    def test_no_stored_state(self) -> None:
        with patch.object(_gaming_reset, "release_block", return_value=[]):
            outcome = _gaming_reset.reset_today(source="ctl")
        assert outcome.seconds_before == 0.0
        assert outcome.released == []
        assert load_state(demo=False) is not None

    def test_history_failure_does_not_undo_the_reset(self) -> None:
        save_state(_spent_state(_today()), demo=False)
        with (
            patch.object(_gaming_reset, "release_block", return_value=[]),
            patch.object(_gaming_reset, "record_day", side_effect=OSError("full")),
        ):
            outcome = _gaming_reset.reset_today(source="ctl")
        assert outcome.seconds_before == 900.0
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.seconds == 0.0
