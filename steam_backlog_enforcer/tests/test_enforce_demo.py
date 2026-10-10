"""Tests for the budget-only ``enforce --demo`` loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._enforce_demo import EXIT_REFUSED, run_demo
from steam_backlog_enforcer.config import Config

PKG = "steam_backlog_enforcer._enforce_demo"


def _echoed(mock_echo: MagicMock) -> str:
    return " ".join(str(c) for c in mock_echo.call_args_list)


def _block(days: float = 2.0) -> SimpleNamespace:
    return SimpleNamespace(days_remaining=days)


class TestRunDemo:
    def test_refuses_to_start_under_a_total_block(self) -> None:
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.get_total_block_status", return_value=_block(2.0)),
            patch(f"{PKG}.playtime_tick") as tick,
            patch(f"{PKG}._echo") as echo,
        ):
            assert run_demo(Config()) == EXIT_REFUSED
        tick.assert_not_called()
        assert "Demo cannot start: total gaming block active (2.0 day(s) left)" in (
            _echoed(echo)
        )

    def test_ticks_only_the_demo_budget_until_interrupted(self) -> None:
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}.new_session", return_value="session") as session,
            patch(f"{PKG}.playtime_tick") as tick,
            patch(f"{PKG}.time.sleep", side_effect=[None, KeyboardInterrupt]),
            patch(f"{PKG}._echo") as echo,
        ):
            assert run_demo(Config()) == 0
        session.assert_called_once_with(demo=True)
        assert tick.call_count == 2
        assert all(c.kwargs["demo"] is True for c in tick.call_args_list)
        assert tick.call_args.kwargs["session"] == "session"
        out = _echoed(echo)
        assert "DEMO MODE" in out
        assert "Runs the budget only" in out
        assert "Demo stopped." in out

    def test_stops_loudly_when_a_total_block_starts_mid_run(self) -> None:
        with (
            patch(f"{PKG}.is_total_block_active", side_effect=[False, False, True]),
            patch(f"{PKG}.get_total_block_status", return_value=_block(1.0)),
            patch(f"{PKG}.new_session"),
            patch(f"{PKG}.playtime_tick") as tick,
            patch(f"{PKG}.time.sleep"),
            patch(f"{PKG}._echo") as echo,
        ):
            assert run_demo(Config()) == EXIT_REFUSED
        tick.assert_called_once()
        assert "Demo stopped: total gaming block active (1.0 day(s) left)" in (
            _echoed(echo)
        )
