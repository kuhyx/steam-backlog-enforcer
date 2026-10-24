"""DLC that ships as its own app: discovery, download, and crediting it in the manifest.

Shapes are taken from the real `app_info_print` of Cyberpunk 2077 (1091500) and
its DLC, 2025-09-25: Phantom Liberty (2138330) keeps its ~25 GB depot under its
own app id; 2060310 is listed in the game's own depots; 2441600 has none.
"""

import logging
import subprocess

import pytest
from _cli_helpers import ARGV, _stub_download, _stub_steamcmd

from steam_installer import appinfo, cli, depotdl, deps, dlc, recognize, runlog, vdf

pytestmark = pytest.mark.usefixtures("cli_logs")

# Every real depot that has content ships a manifest on the public branch.
_PUB = {"manifests": {"public": {"gid": "1"}}}

GAME = {
    "extended": {"listofdlc": "2060310,2138330,2441600"},
    "depots": {
        "1091501": {"config": {"oslist": "windows"}, **_PUB},
        "2060310": {"dlcappid": "2060310", "config": {"oslist": "windows"}, **_PUB},
    },
}
DLC_BLOCKS = {
    # Listed in the game's own depots: the base run already covers it.
    2060310: {"depots": {"2060310": {"dlcappid": "2060310"}}},
    # Its own depot, tagged with its own id -- exactly what it installs.
    2138330: {
        "depots": {
            "2138330": {"dlcappid": "2138330", "config": {"oslist": "windows"}, **_PUB},
            "2138331": {"config": {"oslist": "windows", "language": "german"}, **_PUB},
        }
    },
    2441600: {"common": {"name": "Pre-Order Bonus"}},
}


def _app_info(monkeypatch, game=GAME, dlc_blocks=DLC_BLOCKS):
    monkeypatch.setattr(appinfo, "_fetch_app_block", lambda appid: game)
    monkeypatch.setattr(
        appinfo, "_fetch_app_blocks", lambda ids: {i: dlc_blocks[i] for i in ids}
    )


def test_only_dlc_with_depots_of_its_own_needs_a_run(monkeypatch):
    _app_info(monkeypatch)
    assert appinfo.get_dlc_plans(1091500) == {2138330: {"2138330": "1"}}


@pytest.mark.parametrize("game", [{}, {"extended": "scalar"}, {"extended": {}}])
def test_a_game_without_dlc_needs_no_lookup(monkeypatch, game):
    monkeypatch.setattr(appinfo, "_fetch_app_block", lambda appid: game)
    monkeypatch.setattr(appinfo, "_fetch_app_blocks", lambda ids: pytest.fail())
    assert appinfo.get_dlc_plans(1) == {}


def test_a_game_with_no_depot_list_still_finds_its_dlc(monkeypatch):
    _app_info(monkeypatch, game={"extended": {"listofdlc": "2138330"}})
    assert appinfo.get_dlc_plans(1091500) == {2138330: {"2138330": "1"}}


def test_depot_plan_tags_the_games_own_dlc_depots(monkeypatch):
    _app_info(monkeypatch)
    plan = appinfo.get_depot_plan(1091500)
    assert plan.required == {"1091501"}
    assert plan.dlc == {"2060310": "2060310"}


def test_app_info_for_many_apps_comes_from_one_steamcmd_call(monkeypatch):
    output = (
        'Loading...\n"2060310"\n{\n\t"common"\n\t{\n\t\t"name"\t"A"\n\t}\n}\n'
        '"2138330"\n{\n\t"common"\n\t{\n\t\t"name"\t"B"\n\t}\n}\nUnloading\n'
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

    monkeypatch.setattr(appinfo.subprocess, "run", fake_run)
    blocks = appinfo._fetch_app_blocks([2138330, 2060310])
    assert blocks[2060310]["common"]["name"] == "A"
    assert blocks[2138330]["common"]["name"] == "B"
    assert len(calls) == 1
    assert calls[0].count("+app_info_print") == 2


def _logged(monkeypatch, returncode, output=""):
    monkeypatch.setattr(
        depotdl.runlog, "run_logged", lambda cmd, logger: (returncode, output)
    )


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (0, "", True),
        (1, "App 2441600 (Bonus) is not available from this account.", None),
        (1, "Connection lost", False),
    ],
)
def test_download_dlc_separates_not_owned_from_failed(
    tmp_path, monkeypatch, returncode, output, expected
):
    _logged(monkeypatch, returncode, output)
    result = depotdl.download_dlc(2441600, tmp_path, "u", logging.getLogger("t"))
    assert result is expected


def test_the_managed_depotdownloader_wins_over_path(tmp_path, monkeypatch):
    managed = tmp_path / "depotdownloader"
    managed.write_text("")
    managed.chmod(0o755)
    monkeypatch.setattr(deps, "MANAGED_DEPOTDOWNLOADER", managed)
    assert deps.depotdownloader_bin() == str(managed)


@pytest.fixture
def run_log(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "LOG_DIR", tmp_path / "state")
    log = runlog.setup(1091500)
    yield log
    for handler in list(log.logger.handlers):
        log.logger.removeHandler(handler)
        handler.close()


def _download_owned(monkeypatch, run_log, tmp_path, outcomes):
    monkeypatch.setattr(
        appinfo,
        "get_dlc_plans",
        lambda appid, language: {7: {"70": "g70"}, 8: {"80": "g80"}},
    )
    monkeypatch.setattr(
        depotdl, "download_dlc", lambda dlc_appid, **kw: outcomes[dlc_appid]
    )
    return dlc.download_owned(1, tmp_path, "u", "english", 8, run_log)


def test_owned_dlc_is_returned_and_unowned_skipped(monkeypatch, run_log, tmp_path):
    plan = _download_owned(monkeypatch, run_log, tmp_path, {7: True, 8: None})
    assert (plan.required, plan.dlc) == ({"70"}, {"70": "7"})
    # Its public gid too, so the finish check can prove the DLC's build.
    assert plan.manifests == {"70": "g70"}


def test_a_failed_dlc_download_aborts(monkeypatch, run_log, tmp_path):
    assert _download_owned(monkeypatch, run_log, tmp_path, {7: False, 8: True}) is None


def test_downloaded_dlc_is_required_and_credited_to_its_app(steam, monkeypatch):
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
    _stub_steamcmd(monkeypatch, returncode=8)
    monkeypatch.setattr(dlc, "download_owned", lambda *a: _dlc_plan("100389"))

    assert cli.main(ARGV) == 0

    state = recognize.read_app_state(manifest)
    assert state["InstalledDepots"]["2138330"]["dlcappid"] == "2138330"
    assert "dlcappid" not in state["InstalledDepots"]["1771303"]
    assert "DlcDownloads" not in state


def _dlc_plan(gid):
    return appinfo.DepotPlan(
        {"2138330"}, set(), {"2138330": "2138330"}, {"2138330": gid}
    )


def test_a_stub_with_own_app_dlc_finishes_with_the_proven_build(steam, monkeypatch):
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
    monkeypatch.setattr(dlc, "download_owned", lambda *a: _dlc_plan("100389"))

    assert cli.main([*ARGV, "--skip-steamcmd"]) == 0
    assert recognize.read_app_state(manifest)["buildid"] == "23914554"


def test_a_failed_dlc_download_leaves_the_manifest_alone(steam, monkeypatch):
    library, _ = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    before = recognize.read_app_state(manifest)
    _stub_download(monkeypatch)
    monkeypatch.setattr(dlc, "download_owned", lambda *a: None)

    assert cli.main(ARGV) == 1
    # Only the folder name is fixed up front; nothing claims an install.
    after = recognize.read_app_state(manifest)
    assert after.pop("installdir") == "KingdomComeDeliverance2"
    assert after == before


def test_a_dlc_with_a_malformed_depot_section_is_skipped(monkeypatch):
    _app_info(monkeypatch, dlc_blocks={**DLC_BLOCKS, 2441600: {"depots": "scalar"}})
    assert appinfo.get_dlc_plans(1091500) == {2138330: {"2138330": "1"}}
