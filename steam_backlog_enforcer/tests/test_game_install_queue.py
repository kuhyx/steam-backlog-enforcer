"""Tests for queueing an install with Steam before the fast installer runs.

steam-game-installer only finishes a manifest it finds. A fresh install used
to reach it with none (Oct 22, BG3: "nothing to finish"), so the enforcer now
writes Steam's own "needs downloading" manifest first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.game_install import _queue_download, install_game

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PKG = "steam_backlog_enforcer.game_install"


class TestQueueBeforeFastInstall:
    def test_fast_install_gets_a_manifest_to_finish(self, tmp_path: Path) -> None:
        """steam-game-installer only finishes a manifest it finds, so a fresh
        install is queued with Steam before the installer runs, not after."""
        seen: list[bool] = []

        def fast(_app_id: int, _label: str, prepare: Callable[[], object]) -> bool:
            prepare()
            seen.append((tmp_path / "appmanifest_440.acf").exists())
            return True

        with (
            patch(f"{PKG}.STEAMAPPS_PATH", tmp_path),
            patch(f"{PKG}.fast_install", side_effect=fast),
            patch(f"{PKG}.os.geteuid", return_value=1000),
        ):
            assert install_game(440, "TF2", "s1", use_steam_protocol=True) is True
        assert seen == [True]

    def test_a_manifest_steam_already_has_is_kept(self, tmp_path: Path) -> None:
        """Steam's own download in progress: its manifest is never overwritten."""
        manifest = tmp_path / "appmanifest_440.acf"
        manifest.write_text('"StateFlags"\t\t"1042"\n')
        with (
            patch(f"{PKG}.STEAMAPPS_PATH", tmp_path),
            patch("steam_backlog_enforcer._steam_client.STEAMAPPS_PATH", tmp_path),
        ):
            assert _queue_download(440, "TF2", "s1") is True
        assert manifest.read_text() == '"StateFlags"\t\t"1042"\n'
