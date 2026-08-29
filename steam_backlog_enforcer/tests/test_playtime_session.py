"""Tests for building the per-daemon budget session."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _playtime_log as log_mod
from steam_backlog_enforcer._playtime_engagement import EngagementTracker
from steam_backlog_enforcer._playtime_log import (
    TickJournal,
)
from steam_backlog_enforcer._playtime_session import new_session

PS = "steam_backlog_enforcer._playtime_session"


class TestNewSession:
    def test_builds_a_tracker_and_a_journal(self) -> None:
        with (
            patch(f"{PS}.resolve_desktop_user", return_value="kuhy"),
            patch(f"{PS}.desktop_uid", return_value=1000) as uid,
        ):
            session = new_session()
        assert isinstance(session.tracker, EngagementTracker)
        assert isinstance(session.journal, TickJournal)
        uid.assert_called_once_with("kuhy")

    def test_binds_the_tracker_to_the_desktop_users_runtime_dir(self) -> None:
        # Root's own /run/user/0 would be the wrong place to look for the
        # gatelock holder file.
        with (
            patch(f"{PS}.resolve_desktop_user", return_value="kuhy"),
            patch(f"{PS}.desktop_uid", return_value=1000),
        ):
            session = new_session()
        assert "/run/user/1000/" in str(session.tracker._holder_path)

    def test_demo_journals_away_from_the_production_trail(self) -> None:
        with (
            patch(f"{PS}.resolve_desktop_user", return_value="kuhy"),
            patch(f"{PS}.desktop_uid", return_value=1000),
        ):
            live = new_session()
            demo = new_session(demo=True)
        assert demo.journal._log._path == log_mod.BUDGET_DEMO_LOG_FILE
        assert live.journal._log._path == log_mod.BUDGET_LOG_FILE
