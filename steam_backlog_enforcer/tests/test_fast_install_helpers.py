"""Tests for _fast_install's pure helpers: paths, account, refusal, argv.

The run lifecycle (spawn, poll, fast_install) lives in test_fast_install_runs.py
to keep both files under the 250-line cap.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _fast_install

PKG = "steam_backlog_enforcer._fast_install"


class TestInstallerPath:
    """run.sh is resolved from the desktop user's passwd home."""

    def test_found_in_user_home(self, tmp_path: Path) -> None:
        installer = tmp_path / "src" / "steam-game-installer" / "run.sh"
        installer.parent.mkdir(parents=True)
        installer.write_text("#!/bin/bash\n")
        # The autouse guard points _INSTALLER at a dead absolute path; put the
        # real relative one back so the home join itself is what is tested.
        relative = Path("src", "steam-game-installer", "run.sh")
        with (
            patch.object(_fast_install, "_INSTALLER", relative),
            patch(f"{PKG}.pwd.getpwnam", return_value=SimpleNamespace(pw_dir=tmp_path)),
        ):
            assert _fast_install._installer_path("kuhy") == installer

    def test_missing_file_is_none(self, tmp_path: Path) -> None:
        with patch(
            f"{PKG}.pwd.getpwnam", return_value=SimpleNamespace(pw_dir=tmp_path)
        ):
            assert _fast_install._installer_path("kuhy") is None

    def test_unknown_user_is_none(self) -> None:
        with patch(f"{PKG}.pwd.getpwnam", side_effect=KeyError("nobody")):
            assert _fast_install._installer_path("nobody") is None

    def test_no_user_uses_own_home(self, tmp_path: Path) -> None:
        with patch(f"{PKG}.Path.home", return_value=tmp_path):
            assert _fast_install._installer_path(None) is None


class TestSteamAccountName:
    """The username comes from Steam's own loginusers.vdf."""

    def _write(self, content: str) -> None:
        config = _fast_install.STEAMAPPS_PATH.parent / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "loginusers.vdf").write_text(content)

    def test_reads_account_name(self) -> None:
        self._write('"users"\n{\n\t"7656"\n\t{\n\t\t"AccountName"\t\t"krzys"\n')
        assert _fast_install._steam_account_name() == "krzys"

    def test_no_account_field(self) -> None:
        self._write('"users"\n{\n}\n')
        assert _fast_install._steam_account_name() is None

    def test_missing_file(self) -> None:
        assert _fast_install._steam_account_name() is None


class TestRefusal:
    """Closing Steam is refused while it would destroy something."""

    def test_game_running(self) -> None:
        with patch(f"{PKG}.game_is_running", return_value=True):
            assert "game is running" in (_fast_install._refusal(1) or "")

    def test_other_update_in_progress(self) -> None:
        with (
            patch(f"{PKG}.game_is_running", return_value=False),
            patch(f"{PKG}.steam_update_in_progress", return_value=True) as update,
        ):
            assert "download is in progress" in (_fast_install._refusal(7) or "")
        update.assert_called_once_with(exclude_app_id=7)

    def test_safe(self) -> None:
        with (
            patch(f"{PKG}.game_is_running", return_value=False),
            patch(f"{PKG}.steam_update_in_progress", return_value=False),
        ):
            assert _fast_install._refusal(7) is None


class TestBuildCmd:
    """The argv pins every choice the installer would otherwise prompt for."""

    def test_with_account(self) -> None:
        with (
            patch(f"{PKG}._steam_account_name", return_value="krzys"),
            patch(f"{PKG}.desktop_user_cmd", side_effect=lambda cmd, _u: cmd),
        ):
            cmd = _fast_install._build_cmd(Path("/i/run.sh"), 42, "kuhy")
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
        with (
            patch(f"{PKG}._steam_account_name", return_value=None),
            patch(f"{PKG}.desktop_user_cmd", return_value=["wrapped"]) as wrap,
        ):
            assert _fast_install._build_cmd(Path("/i/run.sh"), 42, "kuhy") == [
                "wrapped"
            ]
        argv, user = wrap.call_args.args
        assert "--username" not in argv
        assert user == "kuhy"


class TestIsFastInstalling:
    """Only this process's own live runs count."""

    def test_tracks_runs(self) -> None:
        assert _fast_install.is_fast_installing(5) is False
        _fast_install._RUNS.append(
            _fast_install._DetachedRun(5, MagicMock(), Path("/nonexistent"))
        )
        assert _fast_install.is_fast_installing(5) is True
        assert _fast_install.is_fast_installing(6) is False
