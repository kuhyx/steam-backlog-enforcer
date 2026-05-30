"""Tests for main CLI module — part 4 (manual pick lock + cmd_pick_manual)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    _MANUAL_LOCK_DAYS,
    _enforce_manual_pick_lock,
    _is_manual_pick_locked,
    _resolve_game_name,
    _show_manual_pick_lock_message,
    cmd_pick_manual,
    cmd_status,
    main,
)
from steam_backlog_enforcer.steam_api import SteamAPIError

PKG = "steam_backlog_enforcer.main"

# A start timestamp that is always within the 14-day lock window.
_STARTED_AT = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
# A start timestamp that is always past the 14-day deadline.
_EXPIRED_AT = (
    datetime.now(timezone.utc) - timedelta(days=_MANUAL_LOCK_DAYS + 1)
).isoformat()


def _locked_state(
    app_id: int = 100,
    name: str = "TestGame",
    started_at: str = _STARTED_AT,
) -> State:
    return State(
        manual_pick_app_id=app_id,
        manual_pick_game_name=name,
        manual_pick_started_at=started_at,
    )


# ──────────────────────────────────────────────────────────────
# _is_manual_pick_locked
# ──────────────────────────────────────────────────────────────


class TestIsManualPickLocked:
    def test_no_manual_pick_not_locked(self) -> None:
        assert _is_manual_pick_locked(State()) is False

    def test_game_finished_not_locked(self) -> None:
        state = _locked_state(app_id=100)
        state.finished_app_ids = [100]
        assert _is_manual_pick_locked(state) is False

    def test_deadline_passed_not_locked(self) -> None:
        state = _locked_state(started_at=_EXPIRED_AT)
        assert _is_manual_pick_locked(state) is False

    def test_active_lock_returns_true(self) -> None:
        state = _locked_state(started_at=_STARTED_AT)
        assert _is_manual_pick_locked(state) is True

    def test_no_started_at_stays_locked(self) -> None:
        # Missing timestamp → cannot determine deadline → stays locked.
        state = _locked_state(started_at="")
        assert _is_manual_pick_locked(state) is True

    def test_invalid_started_at_stays_locked(self) -> None:
        state = _locked_state(started_at="not-a-date")
        assert _is_manual_pick_locked(state) is True


# ──────────────────────────────────────────────────────────────
# _show_manual_pick_lock_message
# ──────────────────────────────────────────────────────────────


class TestShowManualPickLockMessage:
    def test_shows_game_info(self) -> None:
        state = _locked_state(app_id=42, name="MyGame", started_at=_STARTED_AT)
        with patch(f"{PKG}._echo") as mock_echo:
            _show_manual_pick_lock_message(state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "MyGame" in output
        assert "42" in output

    def test_shows_deadline_when_started_at_valid(self) -> None:
        state = _locked_state(started_at=_STARTED_AT)
        with patch(f"{PKG}._echo") as mock_echo:
            _show_manual_pick_lock_message(state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Deadline" in output

    def test_no_crash_on_invalid_started_at(self) -> None:
        state = _locked_state(started_at="bad-date")
        with patch(f"{PKG}._echo"):
            _show_manual_pick_lock_message(state)  # must not raise

    def test_no_crash_on_empty_started_at(self) -> None:
        state = _locked_state(started_at="")
        with patch(f"{PKG}._echo"):
            _show_manual_pick_lock_message(state)  # must not raise


# ──────────────────────────────────────────────────────────────
# _enforce_manual_pick_lock
# ──────────────────────────────────────────────────────────────


class TestEnforceManualPickLock:
    def test_no_lock_passes(self) -> None:
        _enforce_manual_pick_lock("scan", State())  # no exit

    def test_exempt_command_passes_while_locked(self) -> None:
        state = _locked_state()
        _enforce_manual_pick_lock("done", state)  # no exit
        _enforce_manual_pick_lock("status", state)  # no exit

    def test_blocked_command_exits(self) -> None:
        state = _locked_state()
        with (
            patch(f"{PKG}._show_manual_pick_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _enforce_manual_pick_lock("scan", state)
        assert exc_info.value.code == 1

    def test_add_exception_blocked_when_locked(self) -> None:
        state = _locked_state()
        with (
            patch(f"{PKG}._show_manual_pick_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_manual_pick_lock("add-exception", state)

    def test_pick_manual_blocked_when_already_locked(self) -> None:
        state = _locked_state()
        with (
            patch(f"{PKG}._show_manual_pick_lock_message"),
            pytest.raises(SystemExit),
        ):
            _enforce_manual_pick_lock("pick-manual", state)


# ──────────────────────────────────────────────────────────────
# _resolve_game_name
# ──────────────────────────────────────────────────────────────


class TestResolveGameName:
    def test_found_in_snapshot(self) -> None:
        snapshot = [
            {
                "app_id": 440,
                "name": "TF2",
                "total_achievements": 0,
                "unlocked_achievements": 0,
                "playtime_minutes": 0,
            }
        ]
        with patch(f"{PKG}.load_snapshot", return_value=snapshot):
            result = _resolve_game_name(Config(), 440)
        assert result == "TF2"

    def test_not_in_snapshot_found_via_api(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 730, "name": "Counter-Strike 2"}
            ]
            result = _resolve_game_name(Config(), 730)
        assert result == "Counter-Strike 2"

    def test_api_raises_returns_none(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.side_effect = SteamAPIError("fail")
            result = _resolve_game_name(Config(), 999)
        assert result is None

    def test_not_found_anywhere_returns_none(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[{"app_id": 1, "name": "X"}]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [{"appid": 1}]
            result = _resolve_game_name(Config(), 999)
        assert result is None

    def test_no_snapshot_falls_through_to_api(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 440, "name": "TF2"}
            ]
            result = _resolve_game_name(Config(), 440)
        assert result == "TF2"


# ──────────────────────────────────────────────────────────────
# cmd_pick_manual
# ──────────────────────────────────────────────────────────────


class TestCmdPickManual:
    def _base_patches(self) -> dict[str, object]:
        return {
            f"{PKG}._resolve_game_name": "Skyrim SE",
            f"{PKG}.uninstall_other_games": 2,
            f"{PKG}.is_game_installed": False,
            f"{PKG}.install_game": None,
            f"{PKG}.get_all_owned_app_ids": [1, 2, 489830],
            f"{PKG}.hide_other_games": 2,
        }

    def test_invalid_app_id(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_pick_manual(Config(), State(), ["abc"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Error" in output

    def test_game_not_found(self) -> None:
        with (
            patch(f"{PKG}._resolve_game_name", return_value=None),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick_manual(Config(), State(), ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "not found" in output

    def test_aborted_when_not_yes(self) -> None:
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="no"),
            patch(f"{PKG}.State.save") as mock_save,
        ):
            cmd_pick_manual(Config(), State(), ["489830"])
        mock_save.assert_not_called()

    def test_prompts_for_id_when_no_args(self) -> None:
        state = State()
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", side_effect=["489830", "YES"]),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(Config(), state, [])
        assert state.current_app_id == 489830

    def test_success_sets_state_and_runs_post_steps(self) -> None:
        state = State()
        config = Config(uninstall_other_games=True)
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save") as mock_save,
            patch(f"{PKG}.uninstall_other_games", return_value=2) as mock_uninstall,
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game") as mock_install,
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 489830]),
            patch(f"{PKG}.hide_other_games", return_value=1) as mock_hide,
        ):
            cmd_pick_manual(config, state, ["489830"])

        assert state.manual_pick_app_id == 489830
        assert state.manual_pick_game_name == "Skyrim SE"
        assert state.manual_pick_started_at != ""
        assert state.current_app_id == 489830
        mock_save.assert_called_once()
        mock_uninstall.assert_called_once_with(489830)
        mock_install.assert_called_once()
        mock_hide.assert_called_once()

    def test_no_uninstall_when_config_off(self) -> None:
        state = State()
        config = Config(uninstall_other_games=False)
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games") as mock_uninstall,
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(config, state, ["489830"])
        mock_uninstall.assert_not_called()

    def test_game_already_installed_skips_install(self) -> None:
        state = State()
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.install_game") as mock_install,
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        mock_install.assert_not_called()

    def test_no_hide_when_no_owned_ids(self) -> None:
        state = State()
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}.hide_other_games") as mock_hide,
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        mock_hide.assert_not_called()

    def test_uninstall_returns_zero_no_echo(self) -> None:
        state = State()
        config = Config(uninstall_other_games=True)
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(config, state, ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Uninstalled 0" not in output

    def test_enforcement_started_at_set_when_empty(self) -> None:
        state = State(enforcement_started_at="")
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        assert state.enforcement_started_at != ""

    def test_enforcement_started_at_not_overwritten(self) -> None:
        existing_ts = "2026-01-01T00:00:00+00:00"
        state = State(enforcement_started_at=existing_ts)
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        assert state.enforcement_started_at == existing_ts

    def test_hide_returns_zero_no_echo(self) -> None:
        state = State()
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{PKG}.hide_other_games", return_value=0),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Library: hid" not in output


# ──────────────────────────────────────────────────────────────
# main() dispatch to pick-manual
# ──────────────────────────────────────────────────────────────


class TestMainDispatchPickManual:
    def test_dispatches_pick_manual(self) -> None:
        argv = ["prog", "pick-manual", "489830"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch(f"{PKG}.cmd_pick_manual") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once()

    def test_pick_manual_blocked_when_locked(self) -> None:
        state = _locked_state()
        argv = ["prog", "pick-manual", "730"]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=state),
            patch(f"{PKG}._show_manual_pick_lock_message"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1


# ──────────────────────────────────────────────────────────────
# cmd_status shows lock hint when locked
# ──────────────────────────────────────────────────────────────


class TestCmdStatusLockHint:
    def test_shows_lock_hint_when_locked(self) -> None:
        state = _locked_state()
        with (
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "MANUAL PICK LOCK" in output

    def test_no_lock_hint_when_not_locked(self) -> None:
        with (
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_status(Config(), State())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "MANUAL PICK LOCK" not in output
