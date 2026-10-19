"""Tests for building the per-daemon budget session."""

from __future__ import annotations

from steam_backlog_enforcer import _playtime_log as log_mod
from steam_backlog_enforcer._playtime_history import HistoryWriter
from steam_backlog_enforcer._playtime_log import TickJournal
from steam_backlog_enforcer._playtime_session import new_session


class TestNewSession:
    def test_builds_a_journal_and_history(self) -> None:
        session = new_session()
        assert isinstance(session.journal, TickJournal)
        assert isinstance(session.history, HistoryWriter)

    def test_demo_journals_away_from_the_production_trail(self) -> None:
        live = new_session()
        demo = new_session(demo=True)
        assert demo.journal._log._path == log_mod.BUDGET_DEMO_LOG_FILE
        assert live.journal._log._path == log_mod.BUDGET_LOG_FILE

    def test_builds_a_shadow_journal_on_the_same_trail(self) -> None:
        from steam_backlog_enforcer._shadow_log import ShadowJournal

        session = new_session()
        assert isinstance(session.shadow, ShadowJournal)
        assert session.shadow._log._path == log_mod.BUDGET_LOG_FILE
