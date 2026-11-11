"""install_package: pacman -S with named hooks masked for that one call."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _pacman

PKG = "steam_backlog_enforcer._pacman"
HOOK = "guard-lib-block-steam-block.hook"


def _hookdirs(argv: list[str]) -> list[str]:
    """The values of every --hookdir in *argv*, in order."""
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--hookdir"]


class TestInstallPackage:
    """The command line, the mask directory and the outcomes."""

    def test_plain_install_without_masks(self) -> None:
        """Test that no mask means no --hookdir at all (all hooks run)."""
        run = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        with patch(f"{PKG}.subprocess.run", run):
            assert _pacman.install_package("steam") is True
        argv = run.call_args.args[0]
        assert argv[1:] == [_pacman.PACMAN, "-S", "--needed", "--noconfirm", "steam"]

    def test_masked_hook_is_a_dev_null_symlink_in_the_last_hookdir(self) -> None:
        """Test that the mask wins and every other hook directory is kept."""
        seen: dict[str, object] = {}

        def fake_run(argv: list[str], **_kw: object) -> MagicMock:
            dirs = _hookdirs(argv)
            mask = Path(dirs[-1])
            seen["dirs"] = dirs
            seen["entries"] = {p.name: p.readlink() for p in mask.iterdir()}
            seen["mask"] = mask
            return MagicMock(returncode=0, stderr="")

        with patch(f"{PKG}.subprocess.run", side_effect=fake_run):
            assert _pacman.install_package("steam", masked_hooks=(HOOK,)) is True
        dirs = seen["dirs"]
        assert isinstance(dirs, list)
        assert dirs[:2] == ["/usr/share/libalpm/hooks", "/etc/pacman.d/hooks"]
        assert seen["entries"] == {HOOK: Path("/dev/null")}
        mask = seen["mask"]
        assert isinstance(mask, Path)
        assert not mask.exists()

    def test_nonzero_exit_is_false_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that a failed transaction is reported with pacman's stderr."""
        run = MagicMock(return_value=MagicMock(returncode=1, stderr="boom 404"))
        with (
            patch(f"{PKG}.subprocess.run", run),
            caplog.at_level(logging.ERROR),
        ):
            assert _pacman.install_package("steam", masked_hooks=(HOOK,)) is False
        assert "boom 404" in caplog.text

    @pytest.mark.parametrize(
        "error", [OSError("no sudo"), subprocess.TimeoutExpired("pacman", 1)]
    )
    def test_launch_errors_are_false(self, error: Exception) -> None:
        """Test that a missing binary or a timeout never raises."""
        with patch(f"{PKG}.subprocess.run", side_effect=error):
            assert _pacman.install_package("steam") is False

    def test_mask_dir_is_removed_even_when_pacman_fails(self) -> None:
        """Test that no temp directory outlives a failed install."""
        masks: list[Path] = []

        def fake_run(argv: list[str], **_kw: object) -> MagicMock:
            masks.append(Path(_hookdirs(argv)[-1]))
            gone = "gone"
            raise OSError(gone)

        with patch(f"{PKG}.subprocess.run", side_effect=fake_run):
            assert _pacman.install_package("steam", masked_hooks=(HOOK,)) is False
        assert masks
        assert not masks[0].exists()
