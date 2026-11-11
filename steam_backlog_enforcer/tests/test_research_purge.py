"""The Steam folder survives the purge once a research window was used."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._total_block import enforce_total_block_tick
from steam_backlog_enforcer._total_block_purge import (
    _remove_steam_remnants,
    purge_steam_and_proton,
)

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer.tests._total_block_paths import Paths

PKG = "steam_backlog_enforcer._total_block_purge"
BLOCK = "steam_backlog_enforcer._total_block"


def _populate(paths: Paths) -> tuple[Path, Path, Path]:
    """Create the Steam folder (with a save), ~/.steam and ~/steam."""
    save = paths.steam_dir / "steamapps" / "compatdata" / "4197610" / "save.dat"
    save.parent.mkdir(parents=True)
    save.write_text("progress", encoding="utf-8")
    dot_steam, portable = paths.remnant_paths[0], paths.remnant_paths[1]
    dot_steam.mkdir(parents=True)
    portable.mkdir(parents=True)
    return save, dot_steam, portable


class TestKeepSteamDir:
    """Only the Steam data folder is spared; every other remnant still goes."""

    def test_default_purges_the_folder_too(self, total_block_paths: Paths) -> None:
        """Test that without research nothing changed."""
        save, dot_steam, portable = _populate(total_block_paths)
        removed = _remove_steam_remnants()
        assert str(total_block_paths.steam_dir) in removed
        assert not save.exists()
        assert not dot_steam.exists()
        assert not portable.exists()

    def test_kept_folder_and_its_saves_survive(self, total_block_paths: Paths) -> None:
        """Test that the install and local saves are not touched."""
        save, dot_steam, portable = _populate(total_block_paths)
        removed = _remove_steam_remnants(keep_steam_dir=True)
        assert str(total_block_paths.steam_dir) not in removed
        assert save.read_text(encoding="utf-8") == "progress"
        assert not dot_steam.exists()
        assert not portable.exists()

    def test_purge_passes_the_flag_and_logs_only_what_went(
        self, total_block_paths: Paths
    ) -> None:
        """Test that the whole purge honours the flag and logs honestly."""
        save, _, _ = _populate(total_block_paths)
        with patch(f"{PKG}.is_package_installed", return_value=False):
            purge_steam_and_proton(keep_steam_dir=True)
        assert save.exists()
        logged = json.loads(total_block_paths.purge_log_file.read_text("utf-8"))
        assert str(total_block_paths.steam_dir) not in logged[0]["removed_paths"]

    def test_default_purge_still_removes_the_folder(
        self, total_block_paths: Paths
    ) -> None:
        """Test that the old call signature keeps its old behaviour."""
        save, _, _ = _populate(total_block_paths)
        with patch(f"{PKG}.is_package_installed", return_value=False):
            purge_steam_and_proton()
        assert not save.exists()


class TestTickPassesTheFlag:
    """enforce_total_block_tick is the only caller on the hot path."""

    def _tick(self, **kwargs: bool) -> object:
        with (
            patch(f"{BLOCK}.kill_steam_and_launchers", return_value=[]),
            patch(f"{BLOCK}.kill_processes_by_name", return_value=[]),
            patch(f"{BLOCK}.is_steam_installed", return_value=False),
            patch(f"{BLOCK}.apply_total_block_iptables", return_value=True),
            patch(f"{BLOCK}.refresh_total_block_hosts", return_value=True),
            patch(f"{BLOCK}.purge_steam_and_proton") as purge,
        ):
            enforce_total_block_tick(**kwargs)
        return purge

    def test_default_purges_everything(self) -> None:
        """Test that the default is the full purge."""
        purge = self._tick()
        purge.assert_called_once_with(keep_steam_dir=False)

    def test_keep_flag_reaches_the_purge(self) -> None:
        """Test that the research exemption reaches the purge."""
        purge = self._tick(keep_steam_dir=True)
        purge.assert_called_once_with(keep_steam_dir=True)
