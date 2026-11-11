"""Tests for the main CLI: install, uninstall and library-visibility commands."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._steam_errors import SteamUnavailableError
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_hide,
    cmd_install,
    cmd_installed,
    cmd_unhide,
    cmd_uninstall,
)

PKG = "steam_backlog_enforcer.main.install"


class TestCmdInstalled:
    """Tests for cmd_installed."""

    def test_shows_games(self) -> None:
        """Listing assigned and protected installed games runs cleanly."""
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (228980, "RT")],
            ),
            patch(f"{PKG}.is_protected_app", side_effect=lambda aid: aid == 228980),
            patch(f"{PKG}._echo"),
        ):
            cmd_installed(Config(), State(current_app_id=440))


class TestCmdUninstall:
    """Tests for cmd_uninstall."""

    def test_no_game(self) -> None:
        """With no assigned game uninstall says so."""
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_uninstall(Config(), State())
            assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_nothing_to_remove(self) -> None:
        """With only the assigned game installed there is nothing to remove."""
        state = State(current_app_id=440)
        with (
            patch(f"{PKG}.get_installed_games", return_value=[(440, "TF2")]),
            patch(f"{PKG}._echo"),
        ):
            cmd_uninstall(Config(), state)

    def test_confirms_yes(self) -> None:
        """Typing the confirmation phrase uninstalls the other games."""
        state = State(current_app_id=440)
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (730, "CS")],
            ),
            patch(f"{PKG}.uninstall_other_games", return_value=1) as mock_uninstall,
            patch("builtins.input", return_value="uninstall 1 games"),
            patch(f"{PKG}._echo"),
        ):
            cmd_uninstall(Config(), state)
        mock_uninstall.assert_called_once()

    def test_aborts(self) -> None:
        """Any other answer aborts and uninstalls nothing."""
        state = State(current_app_id=440)
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (730, "CS")],
            ),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.uninstall_other_games") as mock_uninstall,
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_uninstall(Config(), state)
            assert any("Aborted" in str(c) for c in mock_echo.call_args_list)
        mock_uninstall.assert_not_called()


class TestCmdInstall:
    """Tests for cmd_install."""

    def test_no_game(self) -> None:
        """With no assigned game install says so."""
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_install(Config(), State())
            assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_already_installed(self) -> None:
        """An already installed game is not installed again."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_fully_installed", return_value=True),
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(), state)

    def test_installs_ok(self) -> None:
        """A successful install of the assigned game runs cleanly."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_fully_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=True),
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(steam_id="i"), state)

    def test_install_fails(self) -> None:
        """A failed install of the assigned game is reported without raising."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_fully_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=False),
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(steam_id="i"), state)

    def test_failed_fast_install_never_says_done(self) -> None:
        """Steam's fallback download started, but the fast one failed: "Done!"
        after the "Failed: ..." line was the success the BG3 job showed."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_fully_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=True),
            patch(f"{PKG}.fast_install_failure", return_value="exit 1"),
            patch(f"{PKG}._echo") as echo,
        ):
            cmd_install(Config(steam_id="i"), state)
        echo.assert_called_with("Steam's own download was started instead.")


class TestCmdHide:
    """Tests for cmd_hide."""

    def test_no_game(self) -> None:
        """Hiding with no assigned game runs cleanly."""
        with patch(f"{PKG}._echo"):
            cmd_hide(Config(), State())

    def test_no_owned(self) -> None:
        """Hiding with no owned games runs cleanly."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}._echo"),
        ):
            cmd_hide(Config(), state)

    def test_hides(self) -> None:
        """Hiding the other owned games runs cleanly."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{PKG}.try_hide_other_games", return_value=(1, None)),
            patch(f"{PKG}._echo"),
        ):
            cmd_hide(Config(), state)

    def test_hides_zero(self) -> None:
        """Hiding zero games runs cleanly."""
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(f"{PKG}.try_hide_other_games", return_value=(0, None)),
            patch(f"{PKG}._echo"),
        ):
            cmd_hide(Config(), state)

    def test_unreachable_steam_reports_skip(self) -> None:
        """An unreachable Steam degrades hiding to a skip message."""
        # Regression guard: a deferred Steam restart used to escape as a
        # traceback instead of degrading to a skip message.
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(
                f"{PKG}.try_hide_other_games",
                return_value=(0, "update in progress"),
            ),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_hide(Config(), state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "skipped (update in progress)" in output
        assert "Hidden" not in output


class TestCmdUnhide:
    """Tests for cmd_unhide."""

    def test_no_owned(self) -> None:
        """Unhiding with no owned games runs cleanly."""
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}._echo"),
        ):
            cmd_unhide(Config(), State())

    def test_unhides(self) -> None:
        """Unhiding owned games runs cleanly."""
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(f"{PKG}.unhide_all_games", return_value=1),
            patch(f"{PKG}._echo"),
        ):
            cmd_unhide(Config(), State())

    def test_skips_without_steam_like_hide(self) -> None:
        """Unhiding without Steam reports a skip, like hide."""
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(
                f"{PKG}.unhide_all_games",
                side_effect=SteamUnavailableError("Steam is not installed"),
            ),
            patch(f"{PKG}._echo") as echo,
        ):
            cmd_unhide(Config(), State())
        echo.assert_called_with("Library unhiding: skipped (Steam is not installed)")

    def test_unhides_zero(self) -> None:
        """Unhiding zero games runs cleanly."""
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(f"{PKG}.unhide_all_games", return_value=0),
            patch(f"{PKG}._echo"),
        ):
            cmd_unhide(Config(), State())


# ──────────────────────────────────────────────────────────────
# cmd_add_exception
# ──────────────────────────────────────────────────────────────

_VALID_REASON = "I need this game installed for a work presentation this week."
