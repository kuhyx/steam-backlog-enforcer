"""Tests for the fast install's pure helpers: paths, account, refusal, argv.

The run lifecycle (spawn, poll, fast_install) lives in test_fast_install_runs.py
to keep both files under the 250-line cap.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _fast_install, _fast_install_cmd, _steam_state
from steam_backlog_enforcer._fast_install import _RUNS, _DetachedRun, _refusal

PKG = "steam_backlog_enforcer._fast_install"
CMD = "steam_backlog_enforcer._fast_install_cmd"


class TestInstallerPath:
    """run.sh is resolved from the desktop user's passwd home."""

    def test_found_in_user_home(self, tmp_path: Path) -> None:
        """run.sh is found under the desktop user's passwd home."""
        installer = tmp_path / "src" / "steam-game-installer" / "run.sh"
        installer.parent.mkdir(parents=True)
        installer.write_text("#!/bin/bash\n")
        # The autouse guard points _INSTALLER at a dead absolute path; put the
        # real relative one back so the home join itself is what is tested.
        relative = Path("src", "steam-game-installer", "run.sh")
        with (
            patch.object(_fast_install_cmd, "_INSTALLER", relative),
            patch(f"{CMD}.pwd.getpwnam", return_value=SimpleNamespace(pw_dir=tmp_path)),
        ):
            assert _fast_install_cmd.installer_path("kuhy") == installer

    def test_missing_file_is_none(self, tmp_path: Path) -> None:
        """A home without run.sh yields no installer."""
        with patch(
            f"{CMD}.pwd.getpwnam", return_value=SimpleNamespace(pw_dir=tmp_path)
        ):
            assert _fast_install_cmd.installer_path("kuhy") is None

    def test_unknown_user_is_none(self) -> None:
        """A user unknown to passwd yields no installer."""
        with patch(f"{CMD}.pwd.getpwnam", side_effect=KeyError("nobody")):
            assert _fast_install_cmd.installer_path("nobody") is None

    def test_no_user_uses_own_home(self, tmp_path: Path) -> None:
        """With no user the process's own home is searched."""
        with patch(f"{CMD}.Path.home", return_value=tmp_path):
            assert _fast_install_cmd.installer_path(None) is None


class TestSteamAccountName:
    """The username comes from Steam's own loginusers.vdf."""

    def _write(self, content: str) -> None:
        config = _fast_install_cmd.STEAMAPPS_PATH.parent / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "loginusers.vdf").write_text(content)

    def test_reads_account_name(self) -> None:
        """The AccountName field is read from loginusers.vdf."""
        self._write('"users"\n{\n\t"7656"\n\t{\n\t\t"AccountName"\t\t"krzys"\n')
        assert _fast_install_cmd.steam_account_name() == "krzys"

    def test_no_account_field(self) -> None:
        """A loginusers.vdf without AccountName yields no name."""
        self._write('"users"\n{\n}\n')
        assert _fast_install_cmd.steam_account_name() is None

    def test_missing_file(self) -> None:
        """A missing loginusers.vdf yields no name."""
        assert _fast_install_cmd.steam_account_name() is None


class TestRefusal:
    """Closing Steam is refused while it would destroy something."""

    def test_game_running(self) -> None:
        """A running game is a reason to refuse closing Steam."""
        with patch(f"{PKG}.game_is_running", return_value=True):
            assert "game is running" in (_refusal() or "")

    def test_other_download_does_not_refuse(self) -> None:
        """Another game's download does not refuse closing Steam."""
        # The installer closes Steam with ``steam -shutdown``, which Steam
        # survives mid-download; another transfer is no reason to skip.
        (_steam_state.STEAMAPPS_PATH / "appmanifest_9.acf").write_text(
            '"AppState"\n{\n\t"BytesToDownload"\t\t"10"\n'
            '\t"BytesDownloaded"\t\t"0"\n}\n'
        )
        assert _steam_state.steam_update_in_progress() is True
        with patch(f"{PKG}.game_is_running", return_value=False):
            assert _refusal() is None


class TestBuildCmd:
    """The argv pins every choice the installer would otherwise prompt for."""

    def test_with_account(self) -> None:
        """A known account adds ``--username`` to the pinned argv."""
        with (
            patch(f"{CMD}.steam_account_name", return_value="krzys"),
            patch(f"{CMD}.desktop_user_cmd", side_effect=lambda cmd, _u: cmd),
        ):
            cmd = _fast_install_cmd.build_cmd(Path("/i/run.sh"), 42, "kuhy")
        assert cmd == [
            "/i/run.sh",
            "--no-deps",
            "--appid",
            "42",
            "--yes",
            "--language",
            "english",
            "--skip-steamcmd",
            "--username",
            "krzys",
        ]

    def test_without_account_and_drops_privileges(self) -> None:
        """No account means no username, and the argv runs as the user."""
        with (
            patch(f"{CMD}.steam_account_name", return_value=None),
            patch(f"{CMD}.desktop_user_cmd", return_value=["wrapped"]) as wrap,
        ):
            assert _fast_install_cmd.build_cmd(Path("/i/run.sh"), 42, "kuhy") == [
                "wrapped"
            ]
        argv, user = wrap.call_args.args
        assert "--username" not in argv
        assert user == "kuhy"


class TestIsFastInstalling:
    """Only this process's own live runs count."""

    def test_tracks_runs(self) -> None:
        """Only app ids with a live run of this process count as installing."""
        assert _fast_install.is_fast_installing(5) is False
        _RUNS.append(_DetachedRun(5, MagicMock(), Path("/nonexistent")))
        assert _fast_install.is_fast_installing(5) is True
        assert _fast_install.is_fast_installing(6) is False
