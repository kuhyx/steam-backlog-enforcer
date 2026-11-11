"""Tests for walking the process tree from the launcher roots."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime_kill import (
    _child_map,
    _own_process_chain,
    _read_ppid,
    descendant_pids,
)

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._playtime_kill"


class TestReadPpid:
    """The parent pid is parsed from /proc/<pid>/stat."""

    def _write_stat(self, tmp_path: Path, pid: int, comm: str, ppid: int) -> None:
        """Write a fake stat line for pid with the given comm and ppid."""
        proc = tmp_path / "playtime_proc" / str(pid)
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text(
            f"{pid} ({comm}) S {ppid} {pid} 0 0 -1 0", encoding="utf-8"
        )

    def test_reads_simple_comm(self, tmp_path: Path) -> None:
        """A plain comm yields the ppid field."""
        self._write_stat(tmp_path, 100, "steam", 1)
        assert _read_ppid(100) == 1

    def test_handles_comm_with_spaces_and_parens(self, tmp_path: Path) -> None:
        """comm can contain both, so field position alone cannot be trusted."""
        self._write_stat(tmp_path, 101, "my game (x) 2", 42)
        assert _read_ppid(101) == 42

    def test_missing_file(self) -> None:
        """A pid with no stat file has no parent."""
        assert _read_ppid(999999) is None

    def test_malformed_stat_too_few_fields(self, tmp_path: Path) -> None:
        """A stat line cut before the ppid gives None."""
        proc = tmp_path / "playtime_proc" / "102"
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text("102 (x) S", encoding="utf-8")
        assert _read_ppid(102) is None

    def test_non_integer_ppid(self, tmp_path: Path) -> None:
        """A non-numeric ppid field gives None."""
        proc = tmp_path / "playtime_proc" / "103"
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text("103 (x) S notanumber 1", encoding="utf-8")
        assert _read_ppid(103) is None


class TestChildMap:
    """The child map groups every /proc pid under its parent."""

    def _write(self, tmp_path: Path, pid: int, ppid: int) -> None:
        """Write a minimal fake stat file for pid under ppid."""
        proc = tmp_path / "playtime_proc" / str(pid)
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text(f"{pid} (p) S {ppid} 1 0", encoding="utf-8")

    def test_builds_mapping(self, tmp_path: Path) -> None:
        """Children are listed under their parent pid."""
        self._write(tmp_path, 10, 1)
        self._write(tmp_path, 11, 10)
        self._write(tmp_path, 12, 10)
        mapping = _child_map()
        assert sorted(mapping[10]) == [11, 12]

    def test_skips_non_digit_entries(self, tmp_path: Path) -> None:
        """Non-pid /proc entries like cpuinfo and self are ignored."""
        (tmp_path / "playtime_proc" / "cpuinfo").touch()
        (tmp_path / "playtime_proc" / "self").mkdir()
        self._write(tmp_path, 20, 1)
        assert 1 in _child_map()

    def test_unreadable_proc_returns_empty(self) -> None:
        """An unlistable /proc gives an empty map."""
        with patch(
            "steam_backlog_enforcer._playtime_block.Path.iterdir",
            side_effect=OSError("nope"),
        ):
            assert _child_map() == {}

    def test_entry_without_stat_is_skipped(self, tmp_path: Path) -> None:
        """A pid directory with no stat file is left out."""
        (tmp_path / "playtime_proc" / "30").mkdir()
        self._write(tmp_path, 31, 1)
        assert 30 not in {c for kids in _child_map().values() for c in kids}


class TestDescendantPids:
    """Descendants are collected below the roots, minus our own chain."""

    def test_walks_the_tree(self) -> None:
        """Children and grandchildren are all returned."""
        tree = {100: [101, 102], 101: [103]}
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill._child_map", return_value=tree
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
        ):
            assert descendant_pids({100}) == {101, 102, 103}

    def test_excludes_the_roots_themselves(self) -> None:
        """The root pids are not in their own descendant set."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill._child_map",
                return_value={100: [101]},
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
        ):
            assert 100 not in descendant_pids({100})

    def test_never_returns_our_own_process(self) -> None:
        """Pids in our own process chain are never returned."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill._child_map",
                return_value={100: [101, 102]},
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value={101},
            ),
        ):
            assert descendant_pids({100}) == {102}

    def test_protected_root_is_not_walked(self) -> None:
        """A root in our own chain is not walked at all."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill._child_map",
                return_value={100: [101]},
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value={100},
            ),
        ):
            assert descendant_pids({100}) == set()

    def test_no_children(self) -> None:
        """A root with no children yields nothing."""
        with (
            patch("steam_backlog_enforcer._playtime_kill._child_map", return_value={}),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
        ):
            assert descendant_pids({100}) == set()

    def test_cycle_terminates(self) -> None:
        """A cyclic tree ends the walk instead of looping."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill._child_map",
                return_value={1: [2], 2: [1]},
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
        ):
            assert descendant_pids({1}) == {2, 1}

    def test_depth_is_bounded(self) -> None:
        """The walk stops at the depth cap."""
        chain = {i: [i + 1] for i in range(1, 100)}
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill._child_map", return_value=chain
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
        ):
            assert len(descendant_pids({1})) == 32


class TestOwnProcessChain:
    """Our own chain runs from this pid up to init."""

    def test_includes_self(self) -> None:
        """The chain always holds our own pid."""
        with patch(
            "steam_backlog_enforcer._playtime_kill._read_ppid", return_value=None
        ):
            assert _own_process_chain() == {os.getpid()}

    def test_walks_to_init(self) -> None:
        """The chain follows ppids until pid 0."""
        with patch(
            "steam_backlog_enforcer._playtime_kill._read_ppid", side_effect=[500, 1, 0]
        ):
            chain = _own_process_chain()
        assert chain == {os.getpid(), 500, 1}

    def test_stops_on_repeat(self) -> None:
        """A ppid that repeats ends the walk."""
        with patch(
            "steam_backlog_enforcer._playtime_kill._read_ppid", return_value=os.getpid()
        ):
            assert _own_process_chain() == {os.getpid()}

    def test_depth_is_bounded(self) -> None:
        """An unbroken ancestor chain must stop at the depth cap, not spin."""
        counter = iter(range(10_000, 20_000))
        with patch(
            "steam_backlog_enforcer._playtime_kill._read_ppid",
            side_effect=lambda _pid: next(counter),
        ):
            assert len(_own_process_chain()) == 32
