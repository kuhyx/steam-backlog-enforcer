"""CLI flow tests, part 2: the manifest-finishing end of a run."""

import subprocess
import sys

import pytest
from _cli_helpers import ARGV, _stub_download

from steam_installer import (
    appinfo,
    cli,
    recognize,
    vdf,
)

pytestmark = pytest.mark.usefixtures("cli_logs")


# The 15 keys Steam accepted on 2026-11-22 (A Space for the Unbound): it
# logged "Fully Installed,App Running", queued no download, and added its own
# LastOwner, UserConfig, MountedConfig, ... on exit.
FROM_SCRATCH_KEYS = [
    "appid", "universe", "name", "StateFlags", "installdir", "LastUpdated",
    "SizeOnDisk", "StagingSize", "buildid", "UpdateResult", "BytesToDownload",
    "BytesDownloaded", "BytesToStage", "BytesStaged", "InstalledDepots",
]


def _proven_plan(monkeypatch, install_dir, shared_owner=None):
    (gid,) = recognize.discover_cached_depot_manifests(install_dir).values()
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan(
            {"1771303"}, set(shared_owner or ()), manifests={"1771303": gid},
            shared_owner=dict(shared_owner or {}),
        ),
    )
    return gid


def test_missing_manifest_is_written_from_scratch(steam, monkeypatch):
    """No steamcmd any more, so nothing else creates the manifest."""
    library, install_dir = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.unlink()
    gid = _proven_plan(monkeypatch, install_dir)
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0

    app_state = vdf.parse(manifest.read_text())["AppState"]
    assert list(app_state) == FROM_SCRATCH_KEYS
    assert app_state["appid"] == "1771300"
    assert app_state["universe"] == "1"
    assert app_state["name"] == "KCD2"
    assert app_state["StateFlags"] == "4"
    assert app_state["installdir"] == "KingdomComeDeliverance2"
    assert app_state["SizeOnDisk"] == "1000"
    assert app_state["buildid"] == "23914554"
    for key in ("StagingSize", "UpdateResult", "BytesToDownload",
                "BytesDownloaded", "BytesToStage", "BytesStaged"):
        assert app_state[key] == "0", key
    assert app_state["InstalledDepots"] == {"1771303": {"manifest": gid, "size": "0"}}
    # Nothing to back up: there was no manifest before.
    assert not manifest.with_suffix(".acf.bak").exists()


def test_a_shared_depot_is_recorded_under_its_owner_from_scratch(steam, monkeypatch):
    """Fixture-only: no shared-depot game was tested live. Steam records a
    depot installed under another app as SharedDepots {depot: owner}."""
    library, install_dir = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.unlink()
    _proven_plan(monkeypatch, install_dir, shared_owner={"228989": "228980"})
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0
    app_state = vdf.parse(manifest.read_text())["AppState"]
    assert app_state["SharedDepots"] == {"228989": "228980"}
    assert "228989" not in app_state["InstalledDepots"]


def test_unproven_content_writes_no_manifest_from_scratch(steam, monkeypatch, capsys):
    """Fail closed: without a proven build there is no buildid to write, and a
    half-true StateFlags=4 manifest is what made Steam redownload games."""
    library, _ = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.unlink()
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 1
    assert not manifest.exists()
    assert "no usable buildid" in capsys.readouterr().out


def test_language_defaults_to_english_when_prompt_is_empty(steam, monkeypatch):
    seen = {}
    monkeypatch.setattr("builtins.input", lambda *a: "y" if "Proceed" in a[0] else "")
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: (
            seen.setdefault("language", language)
            and None
            or appinfo.DepotPlan({"1771303"}, set())
        ),
    )
    _stub_download(monkeypatch)

    cli.main(["--appid", "1771300", "--username", "u"])

    assert seen["language"] == "english"


def test_adopts_staged_content_then_clears_it(steam, monkeypatch, capsys):
    """Steam's staging tree is adopted into the install dir before downloading,
    and only cleared once the install is finished -- never discarded up front."""
    library, install_dir = steam
    staged = library.steamapps / "downloading" / "1771300"
    staged.mkdir(parents=True)
    (staged / "big.pak").write_bytes(b"x" * 2_000_000)
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0

    out = capsys.readouterr().out
    assert "Hardlinking it" in out
    assert "now-redundant Steam staging data" in out
    # Adopted, not copied: the file is one inode with two names.
    assert (install_dir / "big.pak").stat().st_size == 2_000_000


def test_fails_when_written_manifest_does_not_read_back_as_installed(
    steam, monkeypatch, capsys
):
    """Claiming success without re-reading the write is the same fail-open
    mistake in a different place."""
    _stub_download(monkeypatch)
    monkeypatch.setattr(
        recognize, "manifest_reflects_real_install", lambda *a, **kw: False
    )

    assert cli.main(ARGV) == 1
    assert "does not read back as a real install" in capsys.readouterr().out


def test_module_is_runnable_as_a_script(coverage_subprocess_env):
    """`python -m steam_installer.cli` is a real entry point (the __main__
    guard), so it must not be dead code."""
    result = subprocess.run(
        [sys.executable, "-m", "steam_installer.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env=coverage_subprocess_env,
    )
    assert result.returncode == 0
    assert "--skip-steamcmd" not in result.stdout


def test_a_stub_manifest_is_finished_with_the_proven_build(steam, monkeypatch):
    """The enforcer's stub says build 0 and Steam never ran to fill it in. The
    cached depot manifest matching the public branch proves the current build,
    which is what the finished manifest must record (BG3, 2026-10-23)."""
    library, install_dir = steam
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(
        vdf.dumps("AppState", {"appid": "1771300", "StateFlags": "1026", "buildid": "0"})
    )
    (gid,) = recognize.discover_cached_depot_manifests(install_dir).values()
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan(
            {"1771303"}, {"228989"}, manifests={"1771303": gid}
        ),
    )
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0
    app_state = vdf.parse(manifest.read_text())["AppState"]
    assert (app_state["StateFlags"], app_state["buildid"]) == ("4", "23914554")


def test_the_install_folder_is_corrected_even_when_the_download_fails(
    steam, monkeypatch
):
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
