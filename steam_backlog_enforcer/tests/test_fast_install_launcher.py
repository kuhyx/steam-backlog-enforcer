"""The installer ships in this repo: where it is, and the argv that starts it.

The daemon is root and the installer runs as the desktop user, so every piece
of the command line must survive ``sudo``: the interpreter, ``PYTHONPATH`` and
a flag set the installer's own parser accepts. A flag the parser rejects makes
argparse exit 2 and every fast install silently fall back to Steam's download.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _fast_install_cmd
from steam_backlog_enforcer._fast_install_cmd import build_cmd, installer_path
from steam_backlog_enforcer._steam_restart_guard import _INSTALLER_MARKERS
from steam_installer import cli_args

CMD = "steam_backlog_enforcer._fast_install_cmd"
# Read at import: the autouse guard swaps the attribute out before each test.
REAL_INSTALLER: Path = vars(_fast_install_cmd)["_INSTALLER"]
REPO = Path(__file__).resolve().parents[2]


def _argv_after_launcher(cmd: list[str]) -> list[str]:
    """The installer's own arguments: everything after ``-m steam_installer.cli``."""
    return cmd[cmd.index("steam_installer.cli") + 1 :]


class TestInstallerLocation:
    """The installer is found in this checkout, never under ~/src."""

    def test_real_path_is_inside_this_repo(self) -> None:
        """Unpatched, the installer is this repo's own cli module, and exists."""
        assert REAL_INSTALLER == REPO / "steam_installer" / "cli.py"
        assert REAL_INSTALLER.is_file()
        assert "steam-game-installer" not in REAL_INSTALLER.parts

    def test_found_when_present(self) -> None:
        """installer_path returns the repo's cli module."""
        with patch.object(_fast_install_cmd, "_INSTALLER", REAL_INSTALLER):
            assert installer_path() == REAL_INSTALLER

    def test_missing_is_none(self, tmp_path: Path) -> None:
        """A checkout without the installer falls back to Steam's download."""
        with patch.object(_fast_install_cmd, "_INSTALLER", tmp_path / "gone.py"):
            assert installer_path() is None


class TestBuiltArgv:
    """The exact argv the daemon hands to the desktop user."""

    @pytest.fixture(name="argv")
    def _argv(self) -> list[str]:
        with patch(f"{CMD}.steam_account_name", return_value="krzys"):
            return build_cmd(REAL_INSTALLER, 284160, None)

    def test_installer_parser_accepts_it(self, argv: list[str]) -> None:
        """The installer's argparse takes the argv as built, with no exit 2."""
        args = cli_args.build_parser().parse_args(_argv_after_launcher(argv))
        assert args.appid == 284160
        assert args.yes is True
        assert args.language == "english"
        assert args.username == "krzys"

    def test_parser_accepts_it_without_account(self) -> None:
        """No signed-in account means no ``--username``, still parseable."""
        with patch(f"{CMD}.steam_account_name", return_value=None):
            argv = build_cmd(REAL_INSTALLER, 7, None)
        cli_args.build_parser().parse_args(_argv_after_launcher(argv))
        assert "--username" not in argv

    def test_no_run_sh_only_flag(self, argv: list[str]) -> None:
        """``--no-deps`` belongs to run.sh; the module's parser has no such flag."""
        assert "--no-deps" not in argv

    def test_imports_from_this_checkout(self, argv: list[str]) -> None:
        """sudo resets the environment, so PYTHONPATH is named in the argv."""
        assert f"PYTHONPATH={REPO}" in argv
        assert argv[argv.index("steam_installer.cli") - 1] == "-m"

    def test_scan_marker_matches_the_real_cmdline(self, argv: list[str]) -> None:
        """The /proc guard sees the process this argv starts, sudo wrapper too."""
        cmdline = b"\0".join(arg.encode() for arg in argv)
        assert any(marker in cmdline for marker in _INSTALLER_MARKERS)
