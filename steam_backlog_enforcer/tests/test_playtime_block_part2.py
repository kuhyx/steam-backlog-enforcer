"""Tests for applying/releasing the playtime block and the kill walk."""

from __future__ import annotations

import os
import signal
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime_block import (
    _child_map,
    _own_process_chain,
    _read_ppid,
    apply_block,
    block_targets,
    descendant_pids,
    kill_gaming_processes,
    reconcile,
    release_block,
    request_steam_shutdown,
    steam_and_launcher_pids,
)

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._playtime_block"


def _line(mount_point: str) -> str:
    return f"36 25 0:32 / {mount_point} rw,relatime shared:5 - tmpfs tmpfs rw"


def _set_mounted(tmp_path: Path, points: list[Path]) -> None:
    text = "".join(f"{_line(str(p))}\n" for p in points)
    (tmp_path / "mountinfo").write_text(text, encoding="utf-8")


def _make_targets_exist() -> None:
    for target in block_targets():
        target.write_text("#!/bin/sh\nexec real\n", encoding="utf-8")


class TestApplyBlock:
    def test_deferred_while_pacman_holds_the_lock(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        (tmp_path / "db.lck").write_text("", encoding="utf-8")
        with patch(f"{PKG}._run") as mock_run:
            assert apply_block() == []
        mock_run.assert_not_called()

    def test_returns_empty_when_stub_cannot_be_written(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with (
            patch(f"{PKG}._ensure_stub", return_value=False),
            patch(f"{PKG}._run") as mock_run,
        ):
            assert apply_block() == []
        mock_run.assert_not_called()

    def test_mounts_every_existing_target(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with patch(f"{PKG}._run", return_value=True):
            assert apply_block() == list(block_targets())

    def test_skips_missing_targets(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        block_targets()[0].write_text("x", encoding="utf-8")
        with patch(f"{PKG}._run", return_value=True):
            assert apply_block() == [block_targets()[0]]

    def test_skips_already_mounted(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [block_targets()[0]])
        with patch(f"{PKG}._run", return_value=True):
            assert apply_block() == list(block_targets()[1:])

    def test_bind_failure_skips_remount(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with patch(f"{PKG}._run", return_value=False) as mock_run:
            assert apply_block() == []
        # One --bind attempt per target, and no remount followed any of them.
        assert all("--bind" in call.args[0] for call in mock_run.call_args_list)

    def test_remount_failure_is_not_counted(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        # First call (--bind) succeeds, second (remount) fails, repeatedly.
        with patch(f"{PKG}._run", side_effect=[True, False] * 4):
            assert apply_block() == []

    def test_uses_mount_and_remount_argv(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        block_targets()[0].write_text("x", encoding="utf-8")
        with (
            patch(f"{PKG}._run", return_value=True) as mock_run,
            patch(f"{PKG}._mount_bin", return_value="/bin/mount"),
        ):
            apply_block()
        argvs = [call.args[0] for call in mock_run.call_args_list]
        assert argvs[0][:2] == ["/bin/mount", "--bind"]
        assert argvs[1][:3] == ["/bin/mount", "-o", "remount,ro,bind"]


class TestReleaseBlock:
    def test_nothing_mounted(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        with patch(f"{PKG}._run") as mock_run:
            assert release_block() == []
        mock_run.assert_not_called()

    def test_releases_a_single_mount(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])

        def fake_run(_cmd: list[str]) -> bool:
            _set_mounted(tmp_path, [])
            return True

        with patch(f"{PKG}._run", side_effect=fake_run):
            assert release_block() == [target]

    def test_loops_for_stacked_mounts(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        remaining = {"n": 3}

        def fake_run(_cmd: list[str]) -> bool:
            remaining["n"] -= 1
            _set_mounted(tmp_path, [target] if remaining["n"] > 0 else [])
            return True

        with patch(f"{PKG}._run", side_effect=fake_run) as mock_run:
            assert release_block() == [target]
        assert mock_run.call_count == 3

    def test_breaks_when_umount_fails(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        with patch(f"{PKG}._run", return_value=False) as mock_run:
            assert release_block() == []
        assert mock_run.call_count == 1

    def test_bounded_when_umount_never_takes_effect(self, tmp_path: Path) -> None:
        """Always-succeeds-but-never-unmounts must not spin forever."""
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        with patch(f"{PKG}._run", return_value=True) as mock_run:
            assert release_block() == []
        assert mock_run.call_count == 20

    def test_uses_lazy_umount_argv(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        with (
            patch(f"{PKG}._run", return_value=False) as mock_run,
            patch(f"{PKG}._umount_bin", return_value="/bin/umount"),
        ):
            release_block()
        assert mock_run.call_args_list[0].args[0] == ["/bin/umount", "-l", str(target)]


class TestReconcile:
    def test_release_path(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])

        def fake_run(_cmd: list[str]) -> bool:
            _set_mounted(tmp_path, [])
            return True

        with patch(f"{PKG}._run", side_effect=fake_run):
            masked, released = reconcile(should_block=False)
        assert masked == []
        assert released == [target]

    def test_apply_path(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with (
            patch(f"{PKG}._run", return_value=True),
            patch(f"{PKG}.mounts_are_visible", return_value=True),
        ):
            masked, released = reconcile(should_block=True)
        assert masked == list(block_targets())
        assert released == []

    def test_logs_when_mounts_are_invisible(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with (
            patch(f"{PKG}._run", return_value=True),
            patch(f"{PKG}.mounts_are_visible", return_value=False),
            patch(f"{PKG}.logger.error") as mock_error,
        ):
            reconcile(should_block=True)
        mock_error.assert_called_once()

    def test_no_visibility_check_when_nothing_was_masked(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        with (
            patch(f"{PKG}._run", return_value=True),
            patch(f"{PKG}.mounts_are_visible") as mock_visible,
        ):
            reconcile(should_block=True)
        mock_visible.assert_not_called()


class TestRequestSteamShutdown:
    def test_skips_when_steam_is_absent(self) -> None:
        with (
            patch(f"{PKG}.shutil.which", return_value=None),
            patch(f"{PKG}._run") as mock_run,
        ):
            request_steam_shutdown()
        mock_run.assert_not_called()

    def test_sends_shutdown(self) -> None:
        with (
            patch(f"{PKG}.shutil.which", return_value="/usr/bin/steam"),
            patch(f"{PKG}._run", return_value=True) as mock_run,
        ):
            request_steam_shutdown()
        mock_run.assert_called_once_with(["/usr/bin/steam", "-shutdown"])


class TestSteamAndLauncherPids:
    def test_unions_both_name_sets(self) -> None:
        with patch(
            f"{PKG}.get_pids_by_process_names",
            return_value={11: "steam", 22: "lutris"},
        ) as mock_get:
            assert steam_and_launcher_pids() == {11, 22}
        names = mock_get.call_args.args[0]
        assert "steam" in names
        assert "lutris" in names


class TestReadPpid:
    def _write_stat(self, tmp_path: Path, pid: int, comm: str, ppid: int) -> None:
        proc = tmp_path / "playtime_proc" / str(pid)
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text(
            f"{pid} ({comm}) S {ppid} {pid} 0 0 -1 0", encoding="utf-8"
        )

    def test_reads_simple_comm(self, tmp_path: Path) -> None:
        self._write_stat(tmp_path, 100, "steam", 1)
        assert _read_ppid(100) == 1

    def test_handles_comm_with_spaces_and_parens(self, tmp_path: Path) -> None:
        """comm can contain both, so field position alone cannot be trusted."""
        self._write_stat(tmp_path, 101, "my game (x) 2", 42)
        assert _read_ppid(101) == 42

    def test_missing_file(self) -> None:
        assert _read_ppid(999999) is None

    def test_malformed_stat_too_few_fields(self, tmp_path: Path) -> None:
        proc = tmp_path / "playtime_proc" / "102"
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text("102 (x) S", encoding="utf-8")
        assert _read_ppid(102) is None

    def test_non_integer_ppid(self, tmp_path: Path) -> None:
        proc = tmp_path / "playtime_proc" / "103"
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text("103 (x) S notanumber 1", encoding="utf-8")
        assert _read_ppid(103) is None


class TestChildMap:
    def _write(self, tmp_path: Path, pid: int, ppid: int) -> None:
        proc = tmp_path / "playtime_proc" / str(pid)
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "stat").write_text(f"{pid} (p) S {ppid} 1 0", encoding="utf-8")

    def test_builds_mapping(self, tmp_path: Path) -> None:
        self._write(tmp_path, 10, 1)
        self._write(tmp_path, 11, 10)
        self._write(tmp_path, 12, 10)
        mapping = _child_map()
        assert sorted(mapping[10]) == [11, 12]

    def test_skips_non_digit_entries(self, tmp_path: Path) -> None:
        (tmp_path / "playtime_proc" / "cpuinfo").touch()
        (tmp_path / "playtime_proc" / "self").mkdir()
        self._write(tmp_path, 20, 1)
        assert 1 in _child_map()

    def test_unreadable_proc_returns_empty(self) -> None:
        with patch(f"{PKG}.Path.iterdir", side_effect=OSError("nope")):
            assert _child_map() == {}

    def test_entry_without_stat_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "playtime_proc" / "30").mkdir()
        self._write(tmp_path, 31, 1)
        assert 30 not in {c for kids in _child_map().values() for c in kids}


class TestDescendantPids:
    def test_walks_the_tree(self) -> None:
        tree = {100: [101, 102], 101: [103]}
        with (
            patch(f"{PKG}._child_map", return_value=tree),
            patch(f"{PKG}._own_process_chain", return_value=set()),
        ):
            assert descendant_pids({100}) == {101, 102, 103}

    def test_excludes_the_roots_themselves(self) -> None:
        with (
            patch(f"{PKG}._child_map", return_value={100: [101]}),
            patch(f"{PKG}._own_process_chain", return_value=set()),
        ):
            assert 100 not in descendant_pids({100})

    def test_never_returns_our_own_process(self) -> None:
        with (
            patch(f"{PKG}._child_map", return_value={100: [101, 102]}),
            patch(f"{PKG}._own_process_chain", return_value={101}),
        ):
            assert descendant_pids({100}) == {102}

    def test_protected_root_is_not_walked(self) -> None:
        with (
            patch(f"{PKG}._child_map", return_value={100: [101]}),
            patch(f"{PKG}._own_process_chain", return_value={100}),
        ):
            assert descendant_pids({100}) == set()

    def test_no_children(self) -> None:
        with (
            patch(f"{PKG}._child_map", return_value={}),
            patch(f"{PKG}._own_process_chain", return_value=set()),
        ):
            assert descendant_pids({100}) == set()

    def test_cycle_terminates(self) -> None:
        with (
            patch(f"{PKG}._child_map", return_value={1: [2], 2: [1]}),
            patch(f"{PKG}._own_process_chain", return_value=set()),
        ):
            assert descendant_pids({1}) == {2, 1}

    def test_depth_is_bounded(self) -> None:
        chain = {i: [i + 1] for i in range(1, 100)}
        with (
            patch(f"{PKG}._child_map", return_value=chain),
            patch(f"{PKG}._own_process_chain", return_value=set()),
        ):
            assert len(descendant_pids({1})) == 32


class TestOwnProcessChain:
    def test_includes_self(self) -> None:
        with patch(f"{PKG}._read_ppid", return_value=None):
            assert _own_process_chain() == {os.getpid()}

    def test_walks_to_init(self) -> None:
        with patch(f"{PKG}._read_ppid", side_effect=[500, 1, 0]):
            chain = _own_process_chain()
        assert chain == {os.getpid(), 500, 1}

    def test_stops_on_repeat(self) -> None:
        with patch(f"{PKG}._read_ppid", return_value=os.getpid()):
            assert _own_process_chain() == {os.getpid()}

    def test_depth_is_bounded(self) -> None:
        """An unbroken ancestor chain must stop at the depth cap, not spin."""
        counter = iter(range(10_000, 20_000))
        with patch(f"{PKG}._read_ppid", side_effect=lambda _pid: next(counter)):
            assert len(_own_process_chain()) == 32


class TestKillGamingProcesses:
    def test_sigterm_by_default(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value=set()),
            patch(f"{PKG}._own_process_chain", return_value=set()),
            patch(f"{PKG}.os.kill") as mock_kill,
        ):
            assert kill_gaming_processes({7}, force=False) == [7]
        mock_kill.assert_called_once_with(7, signal.SIGTERM)

    def test_sigkill_when_forced(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value=set()),
            patch(f"{PKG}._own_process_chain", return_value=set()),
            patch(f"{PKG}.os.kill") as mock_kill,
        ):
            kill_gaming_processes({7}, force=True)
        mock_kill.assert_called_once_with(7, signal.SIGKILL)

    def test_includes_descendants(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value={8, 9}),
            patch(f"{PKG}._own_process_chain", return_value=set()),
            patch(f"{PKG}.os.kill"),
        ):
            assert kill_gaming_processes({7}, force=False) == [7, 8, 9]

    def test_never_signals_our_own_chain(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value=set()),
            patch(f"{PKG}._own_process_chain", return_value={7}),
            patch(f"{PKG}.os.kill") as mock_kill,
        ):
            assert kill_gaming_processes({7, 8}, force=False) == [8]
        mock_kill.assert_called_once_with(8, signal.SIGTERM)

    def test_process_already_gone(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value=set()),
            patch(f"{PKG}._own_process_chain", return_value=set()),
            patch(f"{PKG}.os.kill", side_effect=ProcessLookupError),
        ):
            assert kill_gaming_processes({7}, force=False) == []

    def test_permission_denied(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value=set()),
            patch(f"{PKG}._own_process_chain", return_value=set()),
            patch(f"{PKG}.os.kill", side_effect=PermissionError),
        ):
            assert kill_gaming_processes({7}, force=False) == []

    def test_empty_set(self) -> None:
        with (
            patch(f"{PKG}.descendant_pids", return_value=set()),
            patch(f"{PKG}._own_process_chain", return_value=set()),
            patch(f"{PKG}.os.kill") as mock_kill,
        ):
            assert kill_gaming_processes(set(), force=False) == []
        mock_kill.assert_not_called()
