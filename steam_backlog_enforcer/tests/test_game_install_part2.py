"""Tests for game_install module — part 2 (missing coverage)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.game_install import (
    _remove_game_dirs,
    uninstall_game,
    uninstall_other_games,
)

if TYPE_CHECKING:
    from pathlib import Path

PKG = "python_pkg.steam_backlog_enforcer.game_install"


class TestRemoveGameDirs:
    """Tests for _remove_game_dirs."""

    def test_removes_install_dir(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "common" / "MyGame"
        install_dir.mkdir(parents=True)
        (install_dir / "game.exe").touch()
        with patch(f"{PKG}.STEAMAPPS_PATH", tmp_path):
            result = _remove_game_dirs(install_dir, 440)
        assert result is True
        assert not install_dir.exists()

    def test_install_dir_none(self, tmp_path: Path) -> None:
        with patch(f"{PKG}.STEAMAPPS_PATH", tmp_path):
            result = _remove_game_dirs(None, 440)
        assert result is True

    def test_install_dir_not_exists(self, tmp_path: Path) -> None:
        missing = tmp_path / "common" / "Missing"
        with patch(f"{PKG}.STEAMAPPS_PATH", tmp_path):
            result = _remove_game_dirs(missing, 440)
        assert result is True

    def test_install_dir_remove_fails(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "common" / "MyGame"
        install_dir.mkdir(parents=True)
        with (
            patch(f"{PKG}.STEAMAPPS_PATH", tmp_path),
            patch(f"{PKG}.shutil.rmtree", side_effect=OSError("perm")),
        ):
            result = _remove_game_dirs(install_dir, 440)
        assert result is False

    def test_removes_cache_dirs(self, tmp_path: Path) -> None:
        for subdir in ("shadercache", "compatdata"):
            (tmp_path / subdir / "440").mkdir(parents=True)
        with patch(f"{PKG}.STEAMAPPS_PATH", tmp_path):
            result = _remove_game_dirs(None, 440)
        assert result is True
        assert not (tmp_path / "shadercache" / "440").exists()
        assert not (tmp_path / "compatdata" / "440").exists()

    def test_cache_dir_remove_oserror_suppressed(self, tmp_path: Path) -> None:
        (tmp_path / "shadercache" / "440").mkdir(parents=True)
        call_count = 0

        def fake_rmtree(_path: object, **_kw: object) -> None:
            nonlocal call_count
            call_count += 1
            msg = "perm"
            raise OSError(msg)

        with (
            patch(f"{PKG}.STEAMAPPS_PATH", tmp_path),
            patch(f"{PKG}.shutil.rmtree", side_effect=fake_rmtree),
        ):
            result = _remove_game_dirs(None, 440)
        assert result is True


class TestUninstallGame:
    """Tests for uninstall_game."""

    def test_success(self, tmp_path: Path) -> None:
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"installdir"\t\t"TF2"\n', encoding="utf-8")
        install_dir = tmp_path / "common" / "TF2"
        install_dir.mkdir(parents=True)
        with patch(f"{PKG}.STEAMAPPS_PATH", tmp_path):
            result = uninstall_game(440, "TF2")
        assert result is True

    def test_manifest_removal_fails(self) -> None:
        mock_manifest = MagicMock()
        mock_manifest.exists.return_value = True
        mock_manifest.unlink.side_effect = OSError
        with (
            patch(f"{PKG}.STEAMAPPS_PATH", MagicMock()),
            patch(f"{PKG}._read_install_dir", return_value=None),
            patch(f"{PKG}._remove_manifest", return_value=False),
            patch(f"{PKG}._remove_game_dirs", return_value=True),
        ):
            result = uninstall_game(440, "TF2")
        assert result is False

    def test_game_dirs_removal_fails(self) -> None:
        with (
            patch(f"{PKG}._read_install_dir", return_value=None),
            patch(f"{PKG}._remove_manifest", return_value=True),
            patch(f"{PKG}._remove_game_dirs", return_value=False),
        ):
            result = uninstall_game(440, "TF2")
        assert result is False


class TestUninstallOtherGames:
    """Tests for uninstall_other_games."""

    def test_keeps_allowed(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (730, "CS")],
            ),
            patch(f"{PKG}.uninstall_game", return_value=True) as mock_uninstall,
        ):
            count = uninstall_other_games(440)
        assert count == 1
        mock_uninstall.assert_called_once_with(730, "CS")

    def test_skips_protected(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(228980, "Redist")],
            ),
            patch(f"{PKG}.uninstall_game") as mock_uninstall,
        ):
            count = uninstall_other_games(None)
        assert count == 0
        mock_uninstall.assert_not_called()

    def test_uninstall_fails(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(999, "GameX")],
            ),
            patch(f"{PKG}.uninstall_game", return_value=False),
        ):
            count = uninstall_other_games(None)
        assert count == 0

    def test_all_allowed_or_protected(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (228980, "Redist")],
            ),
            patch(f"{PKG}.uninstall_game") as mock_uninstall,
        ):
            count = uninstall_other_games(440)
        assert count == 0
        mock_uninstall.assert_not_called()
