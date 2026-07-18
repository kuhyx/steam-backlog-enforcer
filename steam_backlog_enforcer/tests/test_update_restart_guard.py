"""Tests for the 'defer Steam restart while a game update is running' guard.

Covers the manifest transfer scan in ``_steam_state`` and the two restart
paths in ``library_hider`` (the daemon's ``ensure_steam_debug_port`` and the
interactive ``restart_steam``) that must not bounce Steam mid-update.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._steam_state import (
    _manifest_transfer_active,
    steam_update_in_progress,
)
from steam_backlog_enforcer.library_hider import (
    SteamUpdateInProgressError,
    ensure_steam_debug_port,
    restart_steam,
)

if TYPE_CHECKING:
    from pathlib import Path

SS = "steam_backlog_enforcer._steam_state"
LH = "steam_backlog_enforcer.library_hider"


def _manifest(*, to_download: int, downloaded: int, to_stage: int, staged: int) -> str:
    return (
        '"AppState"\n{\n'
        '\t"appid"\t\t"813780"\n'
        f'\t"BytesToDownload"\t\t"{to_download}"\n'
        f'\t"BytesDownloaded"\t\t"{downloaded}"\n'
        f'\t"BytesToStage"\t\t"{to_stage}"\n'
        f'\t"BytesStaged"\t\t"{staged}"\n'
        "}\n"
    )


_DOWNLOADING = _manifest(to_download=100, downloaded=40, to_stage=100, staged=100)
_STAGING = _manifest(to_download=100, downloaded=100, to_stage=100, staged=40)
_IDLE = _manifest(to_download=0, downloaded=0, to_stage=0, staged=0)
_COMPLETE = _manifest(to_download=100, downloaded=100, to_stage=100, staged=100)


def _write(steamapps: Path, app_id: int, body: str) -> Path:
    steamapps.mkdir(parents=True, exist_ok=True)
    manifest = steamapps / f"appmanifest_{app_id}.acf"
    manifest.write_text(body, encoding="utf-8")
    return manifest


class TestManifestTransferActive:
    def test_downloading_is_active(self, tmp_path: Path) -> None:
        assert _manifest_transfer_active(_write(tmp_path, 1, _DOWNLOADING)) is True

    def test_staging_is_active(self, tmp_path: Path) -> None:
        assert _manifest_transfer_active(_write(tmp_path, 1, _STAGING)) is True

    def test_complete_is_inactive(self, tmp_path: Path) -> None:
        assert _manifest_transfer_active(_write(tmp_path, 1, _COMPLETE)) is False

    def test_idle_is_inactive(self, tmp_path: Path) -> None:
        assert _manifest_transfer_active(_write(tmp_path, 1, _IDLE)) is False

    def test_missing_fields_inactive(self, tmp_path: Path) -> None:
        manifest = _write(tmp_path, 1, '"AppState"\n{\n\t"appid"\t\t"1"\n}\n')
        assert _manifest_transfer_active(manifest) is False

    def test_unreadable_manifest_inactive(self, tmp_path: Path) -> None:
        # Never created -> read_text raises OSError -> treated as inactive.
        assert _manifest_transfer_active(tmp_path / "appmanifest_gone.acf") is False


class TestSteamUpdateInProgress:
    def test_true_when_any_app_updating(self, tmp_path: Path) -> None:
        steamapps = tmp_path / "steamapps"
        _write(steamapps, 1, _IDLE)
        _write(steamapps, 2, _DOWNLOADING)
        with patch(f"{SS}.STEAMAPPS_PATH", steamapps):
            assert steam_update_in_progress() is True

    def test_false_when_all_idle(self, tmp_path: Path) -> None:
        steamapps = tmp_path / "steamapps"
        _write(steamapps, 1, _IDLE)
        _write(steamapps, 2, _COMPLETE)
        with patch(f"{SS}.STEAMAPPS_PATH", steamapps):
            assert steam_update_in_progress() is False

    def test_false_when_no_manifests(self, tmp_path: Path) -> None:
        steamapps = tmp_path / "empty_steamapps"
        steamapps.mkdir()
        with patch(f"{SS}.STEAMAPPS_PATH", steamapps):
            assert steam_update_in_progress() is False

    def test_glob_oserror_is_false(self) -> None:
        with patch(f"{SS}.STEAMAPPS_PATH") as fake_path:
            fake_path.glob.side_effect = OSError("boom")
            assert steam_update_in_progress() is False


class TestEnsureSteamDebugPortDefersUpdate:
    def test_defers_and_does_not_shut_down(self) -> None:
        with (
            patch(f"{LH}.steam_is_installed", return_value=True),
            patch(f"{LH}._steam_has_debug_port", return_value=False),
            patch(f"{LH}._is_steam_running", return_value=True),
            patch(f"{LH}.steam_update_in_progress", return_value=True),
            patch(f"{LH}._shutdown_steam") as shutdown,
            patch(f"{LH}._launch_steam_with_debug") as launch,
        ):
            with pytest.raises(SteamUpdateInProgressError):
                ensure_steam_debug_port()
            shutdown.assert_not_called()
            launch.assert_not_called()


class TestRestartSteamGuard:
    def test_skips_when_update_in_progress(self) -> None:
        with (
            patch(f"{LH}.steam_update_in_progress", return_value=True),
            patch(f"{LH}._shutdown_steam") as shutdown,
            patch(f"{LH}._launch_steam_with_debug") as launch,
        ):
            restart_steam()
            shutdown.assert_not_called()
            launch.assert_not_called()

    def test_restarts_when_no_update(self) -> None:
        with (
            patch(f"{LH}.steam_update_in_progress", return_value=False),
            patch(f"{LH}._shutdown_steam") as shutdown,
            patch(f"{LH}._launch_steam_with_debug") as launch,
            patch(f"{LH}._wait_for_cdp_ready", return_value=True),
        ):
            restart_steam()
            shutdown.assert_called_once()
            launch.assert_called_once()
