"""A stub manifest finished with DLC that ships as its own app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_installer import appinfo, cli, dlc, recognize, vdf
from steam_installer.tests._cli_helpers import ARGV, _stub_download

if TYPE_CHECKING:
    from pathlib import Path

    from steam_installer.library import SteamLibrary


pytestmark = pytest.mark.usefixtures("cli_logs")


def _dlc_plan(gid: str) -> appinfo.DepotPlan:
    return appinfo.DepotPlan(
        {"2138330"}, set(), {"2138330": "2138330"}, {"2138330": gid}
    )


def test_a_stub_with_own_app_dlc_finishes_with_the_proven_build(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Base game and its own-app DLC both match the public branch: a build-0
    stub is finished, the DLC's gid coming from the DLC's own app info."""
    library, install_dir = steam
    (install_dir / ".DepotDownloader" / "2138330_100389.manifest").write_bytes(b"x")
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(vdf.dumps("AppState", {"appid": "1771300", "buildid": "0"}))
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan(
            {"1771303"}, set(), manifests={"1771303": "1999516201078544527"}
        ),
    )
    _stub_download(monkeypatch)
    monkeypatch.setattr(dlc, "download_owned", lambda *_: _dlc_plan("100389"))

    assert cli.main(ARGV) == 0
    assert recognize.read_app_state(manifest)["buildid"] == "23914554"


def test_a_failed_dlc_download_leaves_the_manifest_alone(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed dlc download leaves the manifest alone."""
    library, _ = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    before = recognize.read_app_state(manifest)
    _stub_download(monkeypatch)
    monkeypatch.setattr(dlc, "download_owned", lambda *_: None)

    assert cli.main(ARGV) == 1
    # Only the folder name is fixed up front; nothing claims an install.
    after = recognize.read_app_state(manifest)
    assert after.pop("installdir") == "KingdomComeDeliverance2"
    assert after == before


def test_downloaded_dlc_is_required_and_credited_to_its_app(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Downloaded dlc is required and credited to its app."""
    library, install_dir = steam
    (install_dir / ".DepotDownloader" / "2138330_100389.manifest").write_bytes(b"x")
    manifest = library.steamapps / "appmanifest_1771300.acf"
    state = recognize.read_app_state(manifest)
    # Steam's own progress for a DLC download it had started itself.
    state["DlcDownloads"] = {
        "2138330": {"BytesDownloaded": "1", "BytesToDownload": "9"}
    }
    manifest.write_text(vdf.dumps("AppState", state))
    _stub_download(monkeypatch)
    monkeypatch.setattr(dlc, "download_owned", lambda *_: _dlc_plan("100389"))

    assert cli.main(ARGV) == 0

    state = recognize.read_app_state(manifest)
    assert state["InstalledDepots"]["2138330"]["dlcappid"] == "2138330"
    assert "dlcappid" not in state["InstalledDepots"]["1771303"]
    assert "DlcDownloads" not in state
