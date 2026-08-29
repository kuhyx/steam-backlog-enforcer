"""Tests for applying/releasing the playtime block and the kill walk."""

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime_block import (
    apply_block,
    block_targets,
    reconcile,
    release_block,
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
        with patch("steam_backlog_enforcer._playtime_block._run") as mock_run:
            assert apply_block() == []
        mock_run.assert_not_called()

    def test_returns_empty_when_stub_cannot_be_written(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with (
            patch(f"{PKG}._ensure_stub", return_value=False),
            patch("steam_backlog_enforcer._playtime_block._run") as mock_run,
        ):
            assert apply_block() == []
        mock_run.assert_not_called()

    def test_mounts_every_existing_target(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with patch("steam_backlog_enforcer._playtime_block._run", return_value=True):
            assert apply_block() == list(block_targets())

    def test_skips_missing_targets(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        block_targets()[0].write_text("x", encoding="utf-8")
        with patch("steam_backlog_enforcer._playtime_block._run", return_value=True):
            assert apply_block() == [block_targets()[0]]

    def test_skips_already_mounted(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [block_targets()[0]])
        with patch("steam_backlog_enforcer._playtime_block._run", return_value=True):
            assert apply_block() == list(block_targets()[1:])

    def test_bind_failure_skips_remount(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with patch(
            "steam_backlog_enforcer._playtime_block._run", return_value=False
        ) as mock_run:
            assert apply_block() == []
        # One --bind attempt per target, and no remount followed any of them.
        assert all("--bind" in call.args[0] for call in mock_run.call_args_list)

    def test_remount_failure_is_not_counted(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        # First call (--bind) succeeds, second (remount) fails, repeatedly.
        with patch(
            "steam_backlog_enforcer._playtime_block._run", side_effect=[True, False] * 4
        ):
            assert apply_block() == []

    def test_uses_mount_and_remount_argv(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        block_targets()[0].write_text("x", encoding="utf-8")
        with (
            patch(
                "steam_backlog_enforcer._playtime_block._run", return_value=True
            ) as mock_run,
            patch(
                "steam_backlog_enforcer._playtime_block._mount_bin",
                return_value="/bin/mount",
            ),
        ):
            apply_block()
        argvs = [call.args[0] for call in mock_run.call_args_list]
        assert argvs[0][:2] == ["/bin/mount", "--bind"]
        assert argvs[1][:3] == ["/bin/mount", "-o", "remount,ro,bind"]


class TestReleaseBlock:
    def test_nothing_mounted(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        with patch("steam_backlog_enforcer._playtime_block._run") as mock_run:
            assert release_block() == []
        mock_run.assert_not_called()

    def test_releases_a_single_mount(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])

        def fake_run(_cmd: list[str]) -> bool:
            _set_mounted(tmp_path, [])
            return True

        with patch("steam_backlog_enforcer._playtime_block._run", side_effect=fake_run):
            assert release_block() == [target]

    def test_loops_for_stacked_mounts(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        remaining = {"n": 3}

        def fake_run(_cmd: list[str]) -> bool:
            remaining["n"] -= 1
            _set_mounted(tmp_path, [target] if remaining["n"] > 0 else [])
            return True

        with patch(
            "steam_backlog_enforcer._playtime_block._run", side_effect=fake_run
        ) as mock_run:
            assert release_block() == [target]
        assert mock_run.call_count == 3

    def test_breaks_when_umount_fails(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        with patch(
            "steam_backlog_enforcer._playtime_block._run", return_value=False
        ) as mock_run:
            assert release_block() == []
        assert mock_run.call_count == 1

    def test_bounded_when_umount_never_takes_effect(self, tmp_path: Path) -> None:
        """Always-succeeds-but-never-unmounts must not spin forever."""
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        with patch(
            "steam_backlog_enforcer._playtime_block._run", return_value=True
        ) as mock_run:
            assert release_block() == []
        assert mock_run.call_count == 20

    def test_uses_lazy_umount_argv(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _set_mounted(tmp_path, [target])
        with (
            patch(
                "steam_backlog_enforcer._playtime_block._run", return_value=False
            ) as mock_run,
            patch(
                "steam_backlog_enforcer._playtime_block._umount_bin",
                return_value="/bin/umount",
            ),
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

        with patch("steam_backlog_enforcer._playtime_block._run", side_effect=fake_run):
            masked, released = reconcile(should_block=False)
        assert masked == []
        assert released == [target]

    def test_apply_path(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with (
            patch("steam_backlog_enforcer._playtime_block._run", return_value=True),
            patch(f"{PKG}.mounts_are_visible", return_value=True),
        ):
            masked, released = reconcile(should_block=True)
        assert masked == list(block_targets())
        assert released == []

    def test_logs_when_mounts_are_invisible(self, tmp_path: Path) -> None:
        _make_targets_exist()
        _set_mounted(tmp_path, [])
        with (
            patch("steam_backlog_enforcer._playtime_block._run", return_value=True),
            patch(f"{PKG}.mounts_are_visible", return_value=False),
            patch(f"{PKG}.logger.error") as mock_error,
        ):
            reconcile(should_block=True)
        mock_error.assert_called_once()

    def test_no_visibility_check_when_nothing_was_masked(self, tmp_path: Path) -> None:
        _set_mounted(tmp_path, [])
        with (
            patch("steam_backlog_enforcer._playtime_block._run", return_value=True),
            patch(f"{PKG}.mounts_are_visible") as mock_visible,
        ):
            reconcile(should_block=True)
        mock_visible.assert_not_called()
