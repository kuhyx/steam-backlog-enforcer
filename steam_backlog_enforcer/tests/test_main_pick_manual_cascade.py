"""Tests for pick-manual's post-confirmation cascade.

Uninstall, install and library hiding after a confirmed pick. Split from
test_main_pick_manual.py (prompting and state) to keep both under 250 lines.
"""

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_pick_manual,
)
from steam_backlog_enforcer.tests._main_patches import (
    HIDE_OTHERS,
    HIDER_ECHO,
    confirmed_pick,
)

PKG = "steam_backlog_enforcer.main.picks"


class TestPickManualCascade:
    """After a confirmed pick, uninstall, install and hide run only when needed."""

    def test_no_uninstall_when_config_off(self) -> None:
        """With uninstall_other_games off nothing is uninstalled."""
        state = State()
        config = Config(uninstall_other_games=False)
        with confirmed_pick(uninstall=None) as mocks:
            cmd_pick_manual(config, state, ["489830"])
        mocks["uninstall"].assert_not_called()

    def test_game_already_installed_skips_install(self) -> None:
        """An already installed pick is not installed again."""
        state = State()
        with confirmed_pick(), patch(f"{PKG}.install_game") as mock_install:
            cmd_pick_manual(Config(), state, ["489830"])
        mock_install.assert_not_called()

    def test_no_hide_when_no_owned_ids(self) -> None:
        """With no owned app ids the library is not hidden."""
        state = State()
        with confirmed_pick(), patch(HIDE_OTHERS) as mock_hide:
            cmd_pick_manual(Config(), state, ["489830"])
        mock_hide.assert_not_called()

    def test_uninstall_returns_zero_no_echo(self) -> None:
        """Uninstalling zero games prints no uninstall line."""
        state = State()
        config = Config(uninstall_other_games=True)
        with confirmed_pick() as mocks:
            cmd_pick_manual(config, state, ["489830"])
        output = " ".join(str(c) for c in mocks["echo"].call_args_list)
        assert "Uninstalled 0" not in output

    def test_hide_returns_zero_no_echo(self) -> None:
        """Hiding zero games prints no library line."""
        state = State()
        with (
            confirmed_pick(owned=[1, 2]) as mocks,
            patch(HIDE_OTHERS, return_value=(0, None)),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        output = " ".join(str(c) for c in mocks["echo"].call_args_list)
        assert "Library: hid" not in output

    def test_unreachable_steam_reports_skip(self) -> None:
        """A Steam that cannot be driven reports a skip and the pick is kept."""
        # The pick itself must survive a Steam that cannot be driven: this
        # used to abort cmd_pick_manual with a traceback after the pick had
        # already been saved.
        state = State()
        with (
            confirmed_pick(owned=[1, 2]) as mocks,
            patch(HIDER_ECHO, mocks["echo"]),
            patch(HIDE_OTHERS, return_value=(0, "update in progress")),
        ):
            cmd_pick_manual(Config(), state, ["489830"])
        output = " ".join(str(c) for c in mocks["echo"].call_args_list)
        assert "skipped (update in progress)" in output
        assert [p["app_id"] for p in state.manual_picks] == [489830]


# ──────────────────────────────────────────────────────────────
# main() dispatch to pick-manual
# ──────────────────────────────────────────────────────────────
