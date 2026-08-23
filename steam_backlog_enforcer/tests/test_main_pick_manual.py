"""Tests for the main CLI: pick-manual command."""

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_pick_manual,
)

PKG = "steam_backlog_enforcer.main.picks"


class TestCmdPickManual:
    def _base_patches(self) -> dict[str, object]:
        return {
            f"{PKG}._resolve_game_name": "Skyrim SE",
            f"{PKG}.uninstall_other_games": 2,
            f"{PKG}.is_game_installed": False,
            f"{PKG}.install_game": None,
            f"{PKG}.get_all_owned_app_ids": [1, 2, 489830],
            f"{PKG}.try_hide_other_games": (2, None),
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
            patch("steam_backlog_enforcer.config.State.save") as mock_save,
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
            patch(f"{PKG}.try_hide_other_games", return_value=(1, None)) as mock_hide,
        ):
            cmd_pick_manual(config, state, ["489830"])

        assert [p["app_id"] for p in state.manual_picks] == [489830]
        assert state.manual_picks[0]["game_name"] == "Skyrim SE"
        assert state.manual_picks[0]["started_at"] != ""
        assert state.current_app_id == 489830
        mock_save.assert_called_once()
        mock_uninstall.assert_called_once_with({489830})
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
            patch(f"{PKG}.try_hide_other_games") as mock_hide,
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
            patch(f"{PKG}.try_hide_other_games", return_value=(0, None)),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Library: hid" not in output

    def test_unreachable_steam_reports_skip(self) -> None:
        # The pick itself must survive a Steam that cannot be driven: this
        # used to abort cmd_pick_manual with a traceback after the pick had
        # already been saved.
        state = State()
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(
                f"{PKG}.try_hide_other_games",
                return_value=(0, "update in progress"),
            ),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "skipped (update in progress)" in output
        assert [p["app_id"] for p in state.manual_picks] == [489830]


# ──────────────────────────────────────────────────────────────
# main() dispatch to pick-manual
# ──────────────────────────────────────────────────────────────
