"""Tests for _budget_view module — 100% branch coverage."""

from __future__ import annotations

import json
from unittest.mock import patch

from steam_backlog_enforcer import _budget_view as view
from steam_backlog_enforcer import _playtime_state as state_mod
from steam_backlog_enforcer._budget_log_tail import RunningGame, SessionView
from steam_backlog_enforcer._budget_view import (
    CORRUPT,
    DENIED,
    MISSING,
    READABLE,
    build_budget_snapshot,
    build_rules,
    build_today,
    next_warning,
    state_access,
)
from steam_backlog_enforcer._playtime_history import HistoryDay
from steam_backlog_enforcer._playtime_state import PlaytimeState, rules_for
from steam_backlog_enforcer.config import Config

RULES = rules_for(Config(), demo=False)


class TestStateAccess:
    """Tests for telling apart the reasons state fails to load."""

    def test_missing_file(self) -> None:
        assert state_access(state_mod.PLAYTIME_STATE_FILE) == MISSING

    def test_readable_file(self) -> None:
        state_mod.PLAYTIME_STATE_FILE.write_text("{}", encoding="utf-8")
        assert state_access(state_mod.PLAYTIME_STATE_FILE) == READABLE

    def test_unreadable_file(self) -> None:
        state_mod.PLAYTIME_STATE_FILE.write_text("{}", encoding="utf-8")
        with patch("pathlib.Path.read_bytes", side_effect=PermissionError):
            assert state_access(state_mod.PLAYTIME_STATE_FILE) == DENIED


class TestNextWarning:
    """Tests for the forward-looking warning threshold."""

    def test_largest_threshold_below_remaining(self) -> None:
        state = PlaytimeState(day_key="d", seconds=0.0)
        assert next_warning(state, RULES) == 3600

    def test_skips_thresholds_already_fired(self) -> None:
        state = PlaytimeState(day_key="d", seconds=0.0, warned_seconds=[3600])
        assert next_warning(state, RULES) == 1800

    def test_none_once_every_threshold_is_passed(self) -> None:
        state = PlaytimeState(day_key="d", seconds=RULES.budget_seconds)
        assert next_warning(state, RULES) is None

    def test_is_not_the_already_crossed_threshold(self) -> None:
        # pending_warning() would return 3600 here; the display wants the next
        # one the countdown is heading towards.
        state = PlaytimeState(day_key="d", seconds=RULES.budget_seconds - 3000)
        assert next_warning(state, RULES) == 1800


class TestBuildToday:
    """Tests for the today block."""

    def test_reports_usage_and_remaining(self) -> None:
        today = build_today(PlaytimeState(day_key="2026-08-28", seconds=100.0), RULES)
        assert today["seconds_used"] == 100.0
        assert today["seconds_remaining"] == RULES.budget_seconds - 100.0
        assert today["blocked"] is False
        assert today["fraction_used"] < 0.01

    def test_never_reports_negative_remaining(self) -> None:
        today = build_today(PlaytimeState(day_key="d", seconds=10**9), RULES)
        assert today["seconds_remaining"] == 0.0
        assert today["fraction_used"] == 1.0

    def test_reports_the_cutoff(self) -> None:
        today = build_today(
            PlaytimeState(day_key="d", seconds=1.0, blocked_at=2.0), RULES
        )
        assert today["blocked"] is True
        assert today["blocked_at"] == 2.0

    def test_a_zero_budget_reads_as_fully_spent(self) -> None:
        rules = rules_for(Config(daily_gaming_seconds=0), demo=False)
        today = build_today(PlaytimeState(day_key="d", seconds=0.0), rules)
        assert today["fraction_used"] == 1.0


class TestBuildRules:
    """Tests for the rules block."""

    def test_lists_the_policy(self) -> None:
        with patch.object(view, "mounted_targets", return_value=set()):
            rules = build_rules(RULES)
        assert rules["budget_seconds"] == 8 * 3600
        assert rules["warn_at"] == [3600, 1800, 600, 300]
        assert rules["masked_launchers"] == []

    def test_lists_masked_launchers(self) -> None:
        with patch.object(view, "mounted_targets", return_value={"/usr/bin/steam"}):
            assert build_rules(RULES)["masked_launchers"] == ["/usr/bin/steam"]


class TestBuildBudgetSnapshot:
    """Tests for the whole payload."""

    def _snapshot(self, **over: object) -> dict:
        kwargs: dict = {
            "stored": PlaytimeState(day_key="2026-08-28", seconds=100.0),
            "access": READABLE,
            "session": SessionView(available=False),
        }
        kwargs.update(over)
        with (
            patch.object(view, "load_state", return_value=kwargs["stored"]),
            patch.object(view, "state_access", return_value=kwargs["access"]),
            patch.object(view, "last_verdict", return_value=kwargs["session"]),
            patch.object(view, "mounted_targets", return_value=set()),
        ):
            return build_budget_snapshot(demo=bool(kwargs.get("demo", False)))

    def test_reports_a_readable_day(self) -> None:
        snapshot = self._snapshot()
        assert snapshot["readable"] is True
        assert snapshot["state_status"] == READABLE
        assert snapshot["error"] is None
        assert snapshot["today"]["gaming_day"] == "2026-08-28"

    def test_reports_denied_state(self) -> None:
        snapshot = self._snapshot(stored=None, access=DENIED)
        assert snapshot["readable"] is False
        assert snapshot["state_status"] == DENIED
        assert "restart" in snapshot["error"]
        assert snapshot["today"] is None
        # The rest of the payload still comes through.
        assert snapshot["rules"]["budget_seconds"] == 8 * 3600

    def test_reports_missing_state(self) -> None:
        snapshot = self._snapshot(stored=None, access=MISSING)
        assert snapshot["state_status"] == MISSING
        assert "No gaming time" in snapshot["error"]

    def test_a_file_that_opens_but_will_not_parse_is_corrupt(self) -> None:
        snapshot = self._snapshot(stored=None, access=READABLE)
        assert snapshot["state_status"] == CORRUPT
        assert "tampering" in snapshot["error"]

    def test_includes_the_live_session(self) -> None:
        session = SessionView(
            observed_at="2026-08-28T20:42:19+02:00",
            state="engaged",
            reason="engaged",
            causes=["focus"],
            idle_seconds=2.0,
            screen_held=False,
            games=[RunningGame(pid=7, name="hollow_knight")],
            available=True,
        )
        with patch.object(
            view.State, "load", return_value=view.State(current_game_name="HK")
        ):
            block = self._snapshot(session=session)["session"]
        assert block["available"] is True
        assert block["game_name"] == "HK"
        assert block["qualifying_count"] == 1
        assert block["processes"] == [{"pid": 7, "name": "hollow_knight"}]

    def test_includes_recorded_history(self) -> None:
        with patch.object(
            view,
            "load_history",
            return_value=[HistoryDay(day="2026-08-27", seconds=1.5)],
        ):
            snapshot = self._snapshot()
        # A day with a total but no breakdown is entirely unattributed: the
        # residual is computed here, never stored.
        assert snapshot["history"] == [
            {
                "day": "2026-08-27",
                "seconds": 1.5,
                "segments": [{"key": "unattributed", "seconds": 1.5}],
            }
        ]
        assert snapshot["legend"] == [{"key": "unattributed", "label": "Unattributed"}]

    def test_demo_runs_serve_no_history(self) -> None:
        """Production days must not be plotted against the 60-second budget."""
        day = HistoryDay(day="2026-08-28", seconds=28800.0)
        with patch.object(view, "load_history", return_value=[day]) as load:
            snapshot = self._snapshot(demo=True)
        assert snapshot["history"] == []
        assert snapshot["rules"]["demo"] is True
        load.assert_not_called()

    def test_leaks_no_secret(self) -> None:
        """The API key must never cross the HTTP boundary."""
        with patch.object(Config, "load", return_value=Config(steam_api_key="SEKRET")):
            snapshot = self._snapshot()
        assert "SEKRET" not in json.dumps(snapshot)
        assert set(snapshot["rules"]) == {
            "budget_seconds",
            "enforcement",
            "counts_launchers",
            "engagement_gate",
            "idle_grace_seconds",
            "require_game_focus",
            "warn_at",
            "demo",
            "masked_launchers",
        }
