"""The uninstall path's Steam-tool step, on fixture homes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._tool_need import NATIVE_TOOL, STEAM_TOOLS
from steam_backlog_enforcer.game_uninstall import (
    remove_unneeded_tools,
    uninstall_other_games,
)
from steam_backlog_enforcer.tests._appinfo_home import game, write_appinfo
from steam_backlog_enforcer.tests._tool_home import make_home

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer.game_uninstall"
RUNNING = "steam_backlog_enforcer._tool_need.steam_client_running"


@pytest.fixture(name="home")
def fixture_home(tmp_path: Path) -> Iterator[Path]:
    """Point both steamapps bindings at a fixture Steam root."""
    steamapps = tmp_path / "Steam" / "steamapps"
    with (
        patch("steam_backlog_enforcer._steam_state.STEAMAPPS_PATH", steamapps),
        patch(f"{PKG}.STEAMAPPS_PATH", steamapps),
        patch(RUNNING, return_value=False),
    ):
        yield tmp_path / "Steam"


def _tools_left(steamapps: Path) -> set[int]:
    return {
        app_id
        for app_id in STEAM_TOOLS
        if (steamapps / f"appmanifest_{app_id}.acf").exists()
        or (steamapps / "common" / f"dir{app_id}").exists()
    }


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == PKG]


def test_mapped_games_remove_the_tools(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """All mapped: the three tools go, the game stays, one line says why."""
    steamapps = make_home(home, {10: NATIVE_TOOL})
    with caplog.at_level(logging.INFO, logger=PKG):
        assert remove_unneeded_tools() == 3
    assert _tools_left(steamapps) == set()
    assert (steamapps / "appmanifest_10.acf").exists()
    messages = _messages(caplog)
    assert messages[0] == (
        f"removing Steam tools: every installed game runs on {NATIVE_TOOL}"
    )
    assert "Removed manifest for Steam Linux Runtime 4.0 (AppID=4183110)" in messages


def test_unmapped_game_keeps_the_tools(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An unmapped Windows game keeps them with one line naming it."""
    steamapps = make_home(home, {10: NATIVE_TOOL, 20: None})
    write_appinfo(home, {20: game("windows")})
    with caplog.at_level(logging.INFO, logger=PKG):
        assert remove_unneeded_tools() == 0
    assert _tools_left(steamapps) == set(STEAM_TOOLS)
    assert _messages(caplog) == [
        f"kept Steam tools: AppID=20 has no {NATIVE_TOOL} mapping"
    ]


def test_native_game_lets_the_tools_go(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C12: an unmapped native game (DUSK) beside a mapped one: all three go."""
    steamapps = make_home(home, {10: NATIVE_TOOL, 20: None})
    write_appinfo(home, {20: game("windows,linux")})
    with caplog.at_level(logging.INFO, logger=PKG):
        assert remove_unneeded_tools() == 3
    assert _tools_left(steamapps) == set()
    assert (steamapps / "appmanifest_20.acf").exists()
    assert _messages(caplog)[0] == (
        f"removing Steam tools: every installed game runs on {NATIVE_TOOL} or natively"
    )


def test_steam_running_defers(home: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A running Steam defers the decision."""
    steamapps = make_home(home, {10: NATIVE_TOOL})
    with caplog.at_level(logging.INFO, logger=PKG), patch(RUNNING, return_value=True):
        assert remove_unneeded_tools() == 0
    assert _tools_left(steamapps) == set(STEAM_TOOLS)
    assert _messages(caplog) == ["Steam running, deferring tool removal"]


def test_unreadable_config_keeps_and_says_why(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C22: config.vdf unreadable -> tools kept, one line naming the reason."""
    steamapps = make_home(home, {10: NATIVE_TOOL})
    config = home / "config" / "config.vdf"
    config.unlink()
    config.mkdir()
    with caplog.at_level(logging.INFO, logger=PKG):
        assert remove_unneeded_tools() == 0
    assert _tools_left(steamapps) == set(STEAM_TOOLS)
    assert _messages(caplog) == ["kept Steam tools: config.vdf unreadable"]


def test_fast_install_running_keeps_the_tools(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A live fast install keeps them with one line saying so."""
    steamapps = make_home(home, {10: NATIVE_TOOL})
    with (
        caplog.at_level(logging.INFO, logger=PKG),
        patch(
            "steam_backlog_enforcer._tool_need.fast_install_running", return_value=True
        ),
    ):
        assert remove_unneeded_tools() == 0
    assert _tools_left(steamapps) == set(STEAM_TOOLS)
    assert _messages(caplog) == ["kept Steam tools: fast install running"]


def test_no_tools_installed_is_silent(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No tool installed: no decision, no log line."""
    make_home(home, {10: None}, tools=False)
    with (
        caplog.at_level(logging.INFO, logger=PKG),
        patch(f"{PKG}.tool_need") as need,
    ):
        assert remove_unneeded_tools() == 0
    need.assert_not_called()
    assert _messages(caplog) == []


def test_uninstall_sweep_runs_the_step_after_removing_games(home: Path) -> None:
    """The sweep removes the unmapped game first, then the now-unneeded tools.

    The game count it returns still counts games only.
    """
    steamapps = make_home(home, {10: NATIVE_TOOL, 20: None})
    assert uninstall_other_games({10}) == 1
    assert not (steamapps / "appmanifest_20.acf").exists()
    assert _tools_left(steamapps) == set()
