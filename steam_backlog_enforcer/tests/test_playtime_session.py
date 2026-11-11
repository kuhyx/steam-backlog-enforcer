"""Tests for building the per-daemon budget session."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_backlog_enforcer import _playtime_log as log_mod
from steam_backlog_enforcer import _playtime_session as session_mod
from steam_backlog_enforcer._playtime_history import HistoryWriter
from steam_backlog_enforcer._playtime_log import BudgetLog, TickJournal
from steam_backlog_enforcer._playtime_session import new_session
from steam_backlog_enforcer._shadow_log import ShadowJournal

if TYPE_CHECKING:
    from pathlib import Path


class _Wiring:
    """Records which log file each journal new_session builds writes to."""

    def __init__(self) -> None:
        """Start with nothing built."""
        self.log_paths: dict[int, Path] = {}
        self.journal_paths: list[Path] = []
        self.shadow_paths: list[Path] = []


@pytest.fixture(name="wiring")
def fixture_wiring(monkeypatch: pytest.MonkeyPatch) -> _Wiring:
    """Swap the session's log and journal classes for recording subclasses."""
    wiring = _Wiring()

    class SpyLog(BudgetLog):
        """A budget log that remembers the path it was opened on."""

        def __init__(self, *, path: Path) -> None:
            """Record the path, then build the real log."""
            super().__init__(path=path)
            wiring.log_paths[id(self)] = path

    class SpyTick(TickJournal):
        """A tick journal that reports which log it writes through."""

        def __init__(self, log: BudgetLog) -> None:
            """Record the log's path, then build the real journal."""
            super().__init__(log)
            wiring.journal_paths.append(wiring.log_paths[id(log)])

    class SpyShadow(ShadowJournal):
        """A shadow journal that reports which log it writes through."""

        def __init__(self, log: BudgetLog) -> None:
            """Record the log's path, then build the real journal."""
            super().__init__(log)
            wiring.shadow_paths.append(wiring.log_paths[id(log)])

    monkeypatch.setattr(session_mod, "BudgetLog", SpyLog)
    monkeypatch.setattr(session_mod, "TickJournal", SpyTick)
    monkeypatch.setattr(session_mod, "ShadowJournal", SpyShadow)
    return wiring


class TestNewSession:
    """new_session wires the journals to the right audit trail."""

    def test_builds_a_journal_and_history(self) -> None:
        """A session carries a tick journal and a history writer."""
        session = new_session()
        assert isinstance(session.journal, TickJournal)
        assert isinstance(session.history, HistoryWriter)

    def test_demo_journals_away_from_the_production_trail(
        self, wiring: _Wiring
    ) -> None:
        """A demo session journals to the demo file, a live one to production."""
        new_session(demo=True)
        new_session()
        assert wiring.journal_paths == [
            log_mod.BUDGET_DEMO_LOG_FILE,
            log_mod.BUDGET_LOG_FILE,
        ]

    def test_builds_a_shadow_journal_on_the_same_trail(self, wiring: _Wiring) -> None:
        """The shadow journal writes through the game journal's own log."""
        session = new_session()
        assert isinstance(session.shadow, ShadowJournal)
        assert wiring.shadow_paths == [log_mod.BUDGET_LOG_FILE]
        assert len(wiring.log_paths) == 1
