"""The research game slot: approval file, root record and live-session gate."""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _research_game as rg

if TYPE_CHECKING:
    from pathlib import Path

APP = 4197610


def _approve(path: Path, app_id: int = APP, flags: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"app_id": app_id, "added_at": 1.0, "flags": flags or []}),
        encoding="utf-8",
    )


def _wrapper_proc(proc: Path, pid: int, argv0: str = "game_research_desktop") -> None:
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "cmdline").write_bytes(f"/x/bin/{argv0}\0--serve\0".encode())


def test_no_file_means_no_research_game() -> None:
    assert rg.research_game_id() is None
    assert rg.kept_ids() == frozenset()
    assert rg.playable_ids() == frozenset()


def test_file_alone_is_not_honoured() -> None:
    _approve(rg.APPROVAL_FILE)
    assert rg.research_game_id() is None


def test_file_and_record_agree() -> None:
    _approve(rg.APPROVAL_FILE)
    rg.register(APP)
    assert rg.research_game_id() == APP
    assert rg.kept_ids() == frozenset({APP})


def test_file_changed_to_other_app_revokes() -> None:
    _approve(rg.APPROVAL_FILE)
    rg.register(APP)
    _approve(rg.APPROVAL_FILE, app_id=APP + 1)
    assert rg.research_game_id() is None


@pytest.mark.parametrize(
    "text",
    ["", "{", "[]", '{"app_id": "x"}', '{"app_id": true}', '{"app_id": -1}'],
)
def test_malformed_file_fails_closed(text: str) -> None:
    rg.APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    rg.APPROVAL_FILE.write_text(text, encoding="utf-8")
    rg.RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    rg.RECORD_FILE.write_text(json.dumps({"app_id": APP}), encoding="utf-8")
    assert rg.research_game_id() is None


def test_register_refuses_mismatch_and_logs_add() -> None:
    _approve(rg.APPROVAL_FILE)
    with pytest.raises(rg.ResearchGameError):
        rg.register(APP + 1)
    rg.register(APP)
    log = rg.AUDIT_LOG.read_text(encoding="utf-8")
    assert f"RESEARCH_GAME_ADDED app_id={APP}" in log
    assert log.count("\n") == 1


def test_register_refuses_without_file() -> None:
    with pytest.raises(rg.ResearchGameError):
        rg.register(APP)
    assert not rg.RECORD_FILE.exists()


def test_revoke_clears_record_and_logs() -> None:
    _approve(rg.APPROVAL_FILE)
    rg.register(APP)
    assert rg.revoke() == APP
    assert rg.research_game_id() is None
    assert "RESEARCH_GAME_REVOKED" in rg.AUDIT_LOG.read_text(encoding="utf-8")
    assert rg.revoke() is None


def test_playable_only_while_wrapper_flag_live(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    flag = rg.APPROVAL_FILE.parent / "recording.pid"
    _approve(rg.APPROVAL_FILE, flags=[str(flag)])
    rg.register(APP)
    with patch.object(rg, "PROC", proc):
        assert rg.playable_ids() == frozenset()
        flag.write_text("4242", encoding="utf-8")
        assert rg.playable_ids() == frozenset()  # pid not alive
        _wrapper_proc(proc, 4242)
        assert rg.playable_ids() == frozenset({APP})
        flag.unlink()
        assert rg.playable_ids() == frozenset()


def test_flag_owned_by_other_process_is_ignored(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    flag = rg.APPROVAL_FILE.parent / "recording.pid"
    _approve(rg.APPROVAL_FILE, flags=[str(flag)])
    rg.register(APP)
    flag.write_text("77", encoding="utf-8")
    _wrapper_proc(proc, 77, argv0="bash")
    with patch.object(rg, "PROC", proc):
        assert rg.playable_ids() == frozenset()


def test_flag_outside_home_is_ignored(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _wrapper_proc(proc, 5)
    outside = tmp_path / "elsewhere.pid"
    outside.write_text("5", encoding="utf-8")
    _approve(rg.APPROVAL_FILE, flags=[str(outside)])
    rg.register(APP)
    with (
        patch.object(rg, "PROC", proc),
        patch.object(rg, "HOME", rg.APPROVAL_FILE.parent / "home"),
    ):
        assert rg.playable_ids() == frozenset()


def test_stale_launch_flag_is_ignored(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _wrapper_proc(proc, 9)
    flag = rg.APPROVAL_FILE.parent / "research_launch.pid"
    _approve(rg.APPROVAL_FILE, flags=[str(flag)])
    flag.write_text("9", encoding="utf-8")
    rg.register(APP)
    with patch.object(rg, "PROC", proc):
        assert rg.playable_ids() == frozenset({APP})
        old = time.time() - rg.LAUNCH_FLAG_MAX_AGE_S - 5
        os.utime(flag, (old, old))
        assert rg.playable_ids() == frozenset()
