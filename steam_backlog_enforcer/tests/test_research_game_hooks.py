"""The research game is kept installed and visible; killed unless recorded."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _research_game as rg
from steam_backlog_enforcer import _steam_state, library_hider
from steam_backlog_enforcer._enforce_guards import guard_installed_games
from steam_backlog_enforcer._scanning_tampering import _legitimately_played
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.enforcer import enforce_allowed_game
from steam_backlog_enforcer.game_uninstall import uninstall_game, uninstall_other_games
from steam_backlog_enforcer.library_hider import hide_other_games
from steam_backlog_enforcer.tests._no_approved_exceptions import no_approved_exceptions
from steam_backlog_enforcer.tests._zero_ach import ASSIGNED, js_list, recorder

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

RESEARCH = 4197610
OTHER = 570


@pytest.fixture(autouse=True)
def _research_slot() -> Iterator[None]:
    """RESEARCH is approved and registered; no other exception protects."""
    rg.APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    rg.APPROVAL_FILE.write_text(json.dumps({"app_id": RESEARCH}), encoding="utf-8")
    rg.register(RESEARCH)
    yield from no_approved_exceptions()


def _record_live(tmp_path: Path) -> Path:
    """Point the approval file at a live wrapper flag; return the fake /proc."""
    proc = tmp_path / "proc"
    (proc / "31").mkdir(parents=True)
    (proc / "31" / "cmdline").write_bytes(b"game_research_desktop\0")
    flag = rg.APPROVAL_FILE.parent / "recording.pid"
    flag.write_text("31", encoding="utf-8")
    rg.APPROVAL_FILE.write_text(
        json.dumps({"app_id": RESEARCH, "flags": [str(flag)]}), encoding="utf-8"
    )
    return proc


def test_uninstall_sweep_keeps_it() -> None:
    """Uninstall sweep keeps it."""
    removed: list[int] = []
    with (
        patch(
            "steam_backlog_enforcer.game_uninstall.get_installed_games",
            return_value=[(RESEARCH, "Librarian"), (OTHER, "Other")],
        ),
        patch(
            "steam_backlog_enforcer.game_uninstall.uninstall_game",
            side_effect=recorder(removed),
        ),
    ):
        uninstall_other_games({ASSIGNED})
    assert removed == [OTHER]


@pytest.mark.parametrize("strict", [False, True])
def test_install_guard_keeps_it(*, strict: bool) -> None:
    """Install guard keeps it."""
    removed: list[int] = []
    pkg = "steam_backlog_enforcer._enforce_guards"
    with (
        patch(
            f"{pkg}.get_installed_games",
            return_value=[(RESEARCH, "Librarian"), (OTHER, "Other")],
        ),
        patch(f"{pkg}.uninstall_game", side_effect=recorder(removed)),
        patch(f"{pkg}.send_notification"),
    ):
        assert guard_installed_games({ASSIGNED}, strict=strict) == 1
    assert removed == [OTHER]


def test_uninstall_game_refuses_its_files() -> None:
    """Uninstall game refuses its files."""
    steamapps = _steam_state.STEAMAPPS_PATH  # patched per test: read late
    manifest = steamapps / f"appmanifest_{RESEARCH}.acf"
    game_dir = steamapps / "common" / "Librarian"
    game_dir.mkdir(parents=True)
    manifest.write_text('"AppState"\n{\n\t"installdir"\t\t"Librarian"\n}\n')
    assert uninstall_game(RESEARCH, "Librarian") is False
    assert manifest.exists()
    assert game_dir.is_dir()


def test_stays_visible_in_the_library() -> None:
    """The hider's script keeps it in the visible set, off the hide list."""
    evaluate = MagicMock(return_value={})
    with patch.multiple(
        library_hider,
        ensure_steam_debug_port=MagicMock(),
        _evaluate_js=evaluate,
        _cdp_result_value=MagicMock(return_value='{"totalHidden": 0}'),
    ):
        hide_other_games([OTHER, RESEARCH, ASSIGNED], {ASSIGNED})
    script = evaluate.call_args.args[0]
    visible = js_list(r"new Set\((\[.*?\])\)", script)
    hidden = js_list(r"const extraIds = (\[.*?\]);", script)
    assert (RESEARCH in visible, hidden) == (True, [OTHER])


def test_tampering_check_exempts_it() -> None:
    """Tampering check exempts it."""
    assert RESEARCH in _legitimately_played(State(current_app_id=ASSIGNED))


def test_killed_when_not_recording() -> None:
    """Killed when not recording."""
    with (
        patch(
            "steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
            return_value={100: RESEARCH, 200: OTHER},
        ),
        patch("steam_backlog_enforcer.enforcer.kill_process") as kill,
    ):
        assert enforce_allowed_game({ASSIGNED}) == [(100, RESEARCH), (200, OTHER)]
    assert kill.call_count == 2


def test_spared_while_recording(tmp_path: Path) -> None:
    """Spared while recording."""
    with (
        patch.object(rg, "PROC", _record_live(tmp_path)),
        patch(
            "steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
            return_value={100: RESEARCH, 200: OTHER},
        ),
        patch("steam_backlog_enforcer.enforcer.kill_process") as kill,
    ):
        assert enforce_allowed_game({ASSIGNED}) == [(200, OTHER)]
    kill.assert_called_once_with(200, OTHER)


def test_revoked_game_is_treated_normally() -> None:
    """Revoked game is treated normally."""
    rg.APPROVAL_FILE.unlink()
    removed: list[int] = []
    with (
        patch(
            "steam_backlog_enforcer.game_uninstall.get_installed_games",
            return_value=[(RESEARCH, "Librarian")],
        ),
        patch(
            "steam_backlog_enforcer.game_uninstall.uninstall_game",
            side_effect=recorder(removed),
        ),
    ):
        uninstall_other_games({ASSIGNED})
    assert removed == [RESEARCH]
