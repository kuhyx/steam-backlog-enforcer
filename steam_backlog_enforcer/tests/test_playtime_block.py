"""Tests for the playtime block's mount discovery and stub handling."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _playtime_block as blk
from steam_backlog_enforcer._playtime_block import (
    _ensure_stub,
    _mount_bin,
    _umount_bin,
    block_targets,
    mounted_targets,
    mounts_are_visible,
)
from steam_backlog_enforcer._playtime_mountinfo import (
    _mountpoints,
    _unescape_mountinfo,
)
from steam_backlog_enforcer._playtime_run import (
    _run,
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
    """_unescape_mountinfo decodes the octal escapes of mountinfo."""

    def test_space(self) -> None:
        """\\040 decodes to a space."""
        assert _unescape_mountinfo(r"/mnt/my\040dir") == "/mnt/my dir"

    def test_tab_newline_backslash(self) -> None:
        """Tab, newline and backslash escapes decode."""
        assert _unescape_mountinfo(r"a\011b") == "a\tb"
        assert _unescape_mountinfo(r"a\012b") == "a\nb"
        assert _unescape_mountinfo(r"a\134b") == "a\\b"

    def test_plain_string_untouched(self) -> None:
        """A string without escapes is unchanged."""
        assert _unescape_mountinfo("/usr/bin/steam") == "/usr/bin/steam"


class TestMountpoints:
    """_mountpoints reads the mount points out of a mountinfo file."""

    def test_unreadable_file_returns_empty(self, tmp_path: Path) -> None:
        """A missing file yields no mount points."""
        assert _mountpoints(tmp_path / "does-not-exist") == set()

    def test_empty_file(self, tmp_path: Path) -> None:
        """An empty file yields no mount points."""
        path = tmp_path / "mi"
        path.write_text("", encoding="utf-8")
        assert _mountpoints(path) == set()

    def test_skips_short_lines(self, tmp_path: Path) -> None:
        """Lines too short to hold a mount point are skipped."""
        path = tmp_path / "mi"
        path.write_text("1 2 3\n" + _mountinfo_line("/a") + "\n", encoding="utf-8")
        assert {str(p) for p in _mountpoints(path)} == {"/a"}

    def test_decodes_escapes(self, tmp_path: Path) -> None:
        """Mount points are unescaped."""
        path = tmp_path / "mi"
        path.write_text(_mountinfo_line(r"/mnt/a\040b") + "\n", encoding="utf-8")
        assert {str(p) for p in _mountpoints(path)} == {"/mnt/a b"}


class TestMountedTargets:
    """mounted_targets lists only block targets that are mounted."""

    def test_none_mounted(self, tmp_path: Path) -> None:
        """Nothing mounted yields no targets."""
        _write_mountinfo(tmp_path, [])
        assert mounted_targets() == set()

    def test_ignores_unrelated_mounts(self, tmp_path: Path) -> None:
        """Unrelated mounts are not targets."""
        _write_mountinfo(tmp_path, ["/", "/home", "/etc/hosts"])
        assert mounted_targets() == set()

    def test_detects_a_target(self, tmp_path: Path) -> None:
        """A mounted target is found."""
        target = block_targets()[0]
        _write_mountinfo(tmp_path, ["/", str(target)])
        assert mounted_targets() == {target}

    def test_detects_all_targets(self, tmp_path: Path) -> None:
        """All mounted targets are found."""
        _write_mountinfo(tmp_path, [str(t) for t in block_targets()])
        assert mounted_targets() == set(block_targets())


class TestMountsAreVisible:
    """mounts_are_visible checks that init sees our mounts."""

    def test_true_when_nothing_mounted(self, tmp_path: Path) -> None:
        """Nothing mounted counts as visible."""
        _write_mountinfo(tmp_path, [])
        assert mounts_are_visible() is True

    def test_true_when_init_sees_the_mount(self, tmp_path: Path) -> None:
        """A mount init also sees counts as visible."""
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
    """_ensure_stub writes the blocked-gaming stub binary."""

    def test_writes_executable_stub(self, tmp_path: Path) -> None:
        """The stub is written executable with its message."""
        assert _ensure_stub() is True
        stub = tmp_path / "run" / "gaming-blocked"
        assert stub.exists()
        assert stub.stat().st_mode & 0o111
        assert "Gaming blocked" in stub.read_text(encoding="utf-8")

    @pytest.mark.usefixtures("tmp_path")
    def test_idempotent(self) -> None:
        """Writing the stub twice succeeds both times."""
        assert _ensure_stub() is True
        assert _ensure_stub() is True

    def test_returns_false_on_oserror(self) -> None:
        """An OSError makes _ensure_stub return False."""
        with patch(
            "steam_backlog_enforcer._playtime_block.Path.mkdir",
            side_effect=OSError("boom"),
        ):
            assert _ensure_stub() is False


class TestRun:
    """_run reports whether a command exited 0."""

    def test_true_on_zero_exit(self) -> None:
        """Exit 0 is success."""
        with patch(
            "steam_backlog_enforcer._playtime_run.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as mock_run:
            assert _run(["mount", "--bind", "a", "b"]) is True
        mock_run.assert_called_once()

    def test_false_on_nonzero_exit(self) -> None:
        """A non-zero exit is failure."""
        with patch(
            "steam_backlog_enforcer._playtime_run.subprocess.run",
            return_value=MagicMock(returncode=1),
        ):
            assert _run(["mount"]) is False

    def test_false_on_oserror(self) -> None:
        """An OSError is failure."""
        with patch(
            "steam_backlog_enforcer._playtime_run.subprocess.run",
            side_effect=OSError("nope"),
        ):
            assert _run(["mount"]) is False

    def test_false_on_timeout(self) -> None:
        """A timeout is failure."""
        with patch(
            "steam_backlog_enforcer._playtime_run.subprocess.run",
            side_effect=subprocess.TimeoutExpired("mount", 15),
        ):
            assert _run(["mount"]) is False


class TestBinaryResolution:
    """mount and umount resolve via PATH with a /usr/bin fallback."""

    def test_mount_bin_found(self) -> None:
        """mount is taken from PATH."""
        with patch(
            "steam_backlog_enforcer._playtime_block.shutil.which",
            return_value="/bin/mount",
        ):
            assert _mount_bin() == "/bin/mount"

    def test_mount_bin_fallback(self) -> None:
        """mount falls back to /usr/bin/mount."""
        with patch(
            "steam_backlog_enforcer._playtime_block.shutil.which", return_value=None
        ):
            assert _mount_bin() == "/usr/bin/mount"

    def test_umount_bin_found(self) -> None:
        """umount is taken from PATH."""
        with patch(
            "steam_backlog_enforcer._playtime_block.shutil.which",
            return_value="/bin/umount",
        ):
            assert _umount_bin() == "/bin/umount"

    def test_umount_bin_fallback(self) -> None:
        """umount falls back to /usr/bin/umount."""
        with patch(
            "steam_backlog_enforcer._playtime_block.shutil.which", return_value=None
        ):
            assert _umount_bin() == "/usr/bin/umount"


class TestBlockTargets:
    """block_targets exposes the isolated target list."""

    def test_accessor_returns_the_constant(self) -> None:
        """block_targets returns BLOCK_TARGETS."""
        assert block_targets() == blk.BLOCK_TARGETS

    def test_four_targets_are_isolated_in_tests(self) -> None:
        """Guards the conftest patch: these must never be the real binaries."""
        assert len(block_targets()) == 4
        for target in block_targets():
            assert not str(target).startswith("/usr/")
