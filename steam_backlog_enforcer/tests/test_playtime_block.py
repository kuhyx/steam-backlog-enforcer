"""Tests for the playtime block's mount discovery and stub handling."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _playtime_block as blk
from steam_backlog_enforcer._playtime_block import (
    _ensure_stub,
    _mount_bin,
    _mountpoints,
    _run,
    _umount_bin,
    _unescape_mountinfo,
    block_targets,
    mounted_targets,
    mounts_are_visible,
)

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._playtime_block"


def _mountinfo_line(mount_point: str) -> str:
    return f"36 25 0:32 / {mount_point} rw,relatime shared:5 - tmpfs tmpfs rw"


def _write_mountinfo(tmp_path: Path, points: list[str]) -> None:
    (tmp_path / "mountinfo").write_text(
        "\n".join(_mountinfo_line(p) for p in points) + "\n" if points else "",
        encoding="utf-8",
    )


class TestUnescapeMountinfo:
    def test_space(self) -> None:
        assert _unescape_mountinfo(r"/mnt/my\040dir") == "/mnt/my dir"

    def test_tab_newline_backslash(self) -> None:
        assert _unescape_mountinfo(r"a\011b") == "a\tb"
        assert _unescape_mountinfo(r"a\012b") == "a\nb"
        assert _unescape_mountinfo(r"a\134b") == "a\\b"

    def test_plain_string_untouched(self) -> None:
        assert _unescape_mountinfo("/usr/bin/steam") == "/usr/bin/steam"


class TestMountpoints:
    def test_unreadable_file_returns_empty(self, tmp_path: Path) -> None:
        assert _mountpoints(tmp_path / "does-not-exist") == set()

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "mi"
        path.write_text("", encoding="utf-8")
        assert _mountpoints(path) == set()

    def test_skips_short_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "mi"
        path.write_text("1 2 3\n" + _mountinfo_line("/a") + "\n", encoding="utf-8")
        assert {str(p) for p in _mountpoints(path)} == {"/a"}

    def test_decodes_escapes(self, tmp_path: Path) -> None:
        path = tmp_path / "mi"
        path.write_text(_mountinfo_line(r"/mnt/a\040b") + "\n", encoding="utf-8")
        assert {str(p) for p in _mountpoints(path)} == {"/mnt/a b"}


class TestMountedTargets:
    def test_none_mounted(self, tmp_path: Path) -> None:
        _write_mountinfo(tmp_path, [])
        assert mounted_targets() == set()

    def test_ignores_unrelated_mounts(self, tmp_path: Path) -> None:
        _write_mountinfo(tmp_path, ["/", "/home", "/etc/hosts"])
        assert mounted_targets() == set()

    def test_detects_a_target(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _write_mountinfo(tmp_path, ["/", str(target)])
        assert mounted_targets() == {target}

    def test_detects_all_targets(self, tmp_path: Path) -> None:
        _write_mountinfo(tmp_path, [str(t) for t in block_targets()])
        assert mounted_targets() == set(block_targets())


class TestMountsAreVisible:
    def test_true_when_nothing_mounted(self, tmp_path: Path) -> None:
        _write_mountinfo(tmp_path, [])
        assert mounts_are_visible() is True

    def test_true_when_init_sees_the_mount(self, tmp_path: Path) -> None:
        target = block_targets()[0]
        _write_mountinfo(tmp_path, [str(target)])
        (tmp_path / "init_mountinfo").write_text(
            _mountinfo_line(str(target)) + "\n", encoding="utf-8"
        )
        assert mounts_are_visible() is True

    def test_false_when_init_cannot_see_it(self, tmp_path: Path) -> None:
        """A private mount namespace would look exactly like this."""
        target = block_targets()[0]
        _write_mountinfo(tmp_path, [str(target)])
        (tmp_path / "init_mountinfo").write_text(
            _mountinfo_line("/unrelated") + "\n", encoding="utf-8"
        )
        assert mounts_are_visible() is False


class TestEnsureStub:
    def test_writes_executable_stub(self, tmp_path: Path) -> None:
        assert _ensure_stub() is True
        stub = tmp_path / "run" / "gaming-blocked"
        assert stub.exists()
        assert stub.stat().st_mode & 0o111
        assert "Gaming blocked" in stub.read_text(encoding="utf-8")

    def test_idempotent(self, tmp_path: Path) -> None:
        assert _ensure_stub() is True
        assert _ensure_stub() is True

    def test_returns_false_on_oserror(self) -> None:
        with patch(f"{PKG}.Path.mkdir", side_effect=OSError("boom")):
            assert _ensure_stub() is False


class TestRun:
    def test_true_on_zero_exit(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as mock_run:
            assert _run(["mount", "--bind", "a", "b"]) is True
        mock_run.assert_called_once()

    def test_false_on_nonzero_exit(self) -> None:
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _run(["mount"]) is False

    def test_false_on_oserror(self) -> None:
        with patch(f"{PKG}.subprocess.run", side_effect=OSError("nope")):
            assert _run(["mount"]) is False

    def test_false_on_timeout(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            side_effect=subprocess.TimeoutExpired("mount", 15),
        ):
            assert _run(["mount"]) is False


class TestBinaryResolution:
    def test_mount_bin_found(self) -> None:
        with patch(f"{PKG}.shutil.which", return_value="/bin/mount"):
            assert _mount_bin() == "/bin/mount"

    def test_mount_bin_fallback(self) -> None:
        with patch(f"{PKG}.shutil.which", return_value=None):
            assert _mount_bin() == "/usr/bin/mount"

    def test_umount_bin_found(self) -> None:
        with patch(f"{PKG}.shutil.which", return_value="/bin/umount"):
            assert _umount_bin() == "/bin/umount"

    def test_umount_bin_fallback(self) -> None:
        with patch(f"{PKG}.shutil.which", return_value=None):
            assert _umount_bin() == "/usr/bin/umount"


class TestBlockTargets:
    def test_accessor_returns_the_constant(self) -> None:
        assert block_targets() == blk.BLOCK_TARGETS

    def test_four_targets_are_isolated_in_tests(self) -> None:
        """Guards the conftest patch: these must never be the real binaries."""
        assert len(block_targets()) == 4
        for target in block_targets():
            assert not str(target).startswith("/usr/")
