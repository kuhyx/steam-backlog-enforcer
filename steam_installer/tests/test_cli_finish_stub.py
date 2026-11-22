"""CLI flow tests, part 3: stub manifests and the script entry point."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from steam_installer import (
    cli,
    recognize,
    vdf,
)
from steam_installer.tests._cli_helpers import ARGV, _stub_download, proven_plan

if TYPE_CHECKING:
    from pathlib import Path

    from steam_installer.library import SteamLibrary

pytestmark = pytest.mark.usefixtures("cli_logs")


def test_module_is_runnable_as_a_script(
    coverage_subprocess_env: dict[str, str],
) -> None:
    """`python -m steam_installer.cli` is a real entry point (the __main__
    guard), so it must not be dead code."""
    result = subprocess.run(
        [sys.executable, "-m", "steam_installer.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env=coverage_subprocess_env,
        check=False,
    )
    assert result.returncode == 0
    assert "--skip-steamcmd" not in result.stdout


def test_a_stub_manifest_is_finished_with_the_proven_build(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enforcer's stub says build 0 and Steam never ran to fill it in. The
    cached depot manifest matching the public branch proves the current build,
    which is what the finished manifest must record (BG3, 2026-10-23)."""
    library, install_dir = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(
        vdf.dumps(
            "AppState", {"appid": "1771300", "StateFlags": "1026", "buildid": "0"}
        )
    )
    proven_plan(monkeypatch, install_dir, shared={"228989"})
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0
    app_state = vdf.parse(manifest.read_text())["AppState"]
    assert (app_state["StateFlags"], app_state["buildid"]) == ("4", "23914554")


def test_the_install_folder_is_corrected_even_when_the_download_fails(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enforcer's stub names the folder after the display name ("Baldur's
    Gate 3", not "Baldurs Gate 3"). Steam resumes onto whatever the manifest
    says, so it is fixed as soon as Steam is closed, not only on success."""
    library, _ = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    state = recognize.read_app_state(manifest)
    state["installdir"] = "Kingdom Come: Deliverance II"
    manifest.write_text(vdf.dumps("AppState", state))
    _stub_download(monkeypatch, returncode=2)

    assert cli.main(ARGV) == 1
    assert recognize.read_app_state(manifest)["installdir"] == "KingdomComeDeliverance2"


def test_wrong_installdir_and_mismatched_counters_end_correct_and_zeroed(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C18: the live repro (installdir "... WRONG", BytesToDownload 1000,
    BytesDownloaded 5) once came out as 1000/1000. The written manifest must
    name the real folder, keep its files, and carry every counter at 0."""
    library, install_dir = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    state = recognize.read_app_state(manifest)
    state.update(
        installdir="KingdomComeDeliverance2 WRONG",
        BytesToDownload="1000",
        BytesDownloaded="5",
        BytesToStage="1000",
        BytesStaged="5",
    )
    manifest.write_text(vdf.dumps("AppState", state))
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0

    app_state = recognize.read_app_state(manifest)
    assert app_state["installdir"] == "KingdomComeDeliverance2"
    assert (install_dir / "game.pak").stat().st_size == 1000
    for key in ("BytesToDownload", "BytesDownloaded", "BytesToStage", "BytesStaged"):
        assert app_state[key] == "0", key
