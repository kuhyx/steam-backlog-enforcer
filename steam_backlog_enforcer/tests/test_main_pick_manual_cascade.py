"""Tests for pick-manual's post-confirmation cascade.

Uninstall, install and library hiding after a confirmed pick. Split from
test_main_pick_manual.py (prompting and state) to keep both under 250 lines.
"""

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_pick_manual,
)

PKG = "steam_backlog_enforcer.main.picks"


class TestPickManualCascade:
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
            patch(
                "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
                return_value=[],
            ),
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
            patch(
                "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
                return_value=[],
            ),
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
            patch(
                "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
                return_value=[],
            ),
            patch(
                "steam_backlog_enforcer.library_hider.try_hide_other_games"
            ) as mock_hide,
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
            patch(
                "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
                return_value=[],
            ),
        ):
            cmd_pick_manual(config, state, ["489830"])
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Uninstalled 0" not in output

    def test_hide_returns_zero_no_echo(self) -> None:
        state = State()
        with (
            patch(f"{PKG}._resolve_game_name", return_value="Skyrim SE"),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(
                "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
                return_value=[1, 2],
            ),
            patch(
                "steam_backlog_enforcer.library_hider.try_hide_other_games",
                return_value=(0, None),
            ),
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
            # The skip line is printed by the shared hide helper.
            patch("steam_backlog_enforcer.library_hider._echo", mock_echo),
            patch("builtins.input", return_value="YES"),
            patch.object(State, "save"),
            patch(f"{PKG}.uninstall_other_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(
                "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
                return_value=[1, 2],
            ),
            patch(
                "steam_backlog_enforcer.library_hider.try_hide_other_games",
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
