"""CLI flow tests, part 2: the manifest-finishing end of a run."""

import subprocess
import sys

import pytest
from steam_installer import (
    appinfo,
    cli,
    recognize,
    vdf,
)

from _cli_helpers import ARGV, _stub_download, _stub_steamcmd

pytestmark = pytest.mark.usefixtures("cli_logs")


def test_missing_manifest_under_skip_steamcmd_does_not_blame_steamcmd(
    steam, monkeypatch, capsys
):
    """--skip-steamcmd never runs steamcmd, so "steamcmd never ran far enough"
    would send the user chasing the wrong thing."""
    library, _ = steam
    (library.steamapps / "appmanifest_1771300.acf").unlink()
    _stub_download(monkeypatch)

    assert cli.main([*ARGV, "--skip-steamcmd"]) == 1

    out = capsys.readouterr().out
    assert "never fabricates one" in out
    assert "Re-run without --skip-steamcmd" in out
    assert "steamcmd never ran far enough" not in out


def test_missing_manifest_with_steamcmd_blames_steamcmd(steam, monkeypatch, capsys):
    library, _ = steam
    (library.steamapps / "appmanifest_1771300.acf").unlink()
    _stub_download(monkeypatch)
    _stub_steamcmd(monkeypatch, returncode=8)

    assert cli.main(ARGV) == 1
    assert "steamcmd never ran far enough" in capsys.readouterr().out


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
    _stub_steamcmd(monkeypatch, returncode=8)

    cli.main(["--appid", "1771300", "--username", "u"])

    assert seen["language"] == "english"


def test_reports_the_known_install_script_crash(steam, monkeypatch, capsys):
    _stub_download(monkeypatch)
    _stub_steamcmd(monkeypatch, returncode=-11, crashed=True)

    assert cli.main(ARGV) == 0
    assert "known install-script crash" in capsys.readouterr().out


def test_adopts_staged_content_then_clears_it(steam, monkeypatch, capsys):
    """Steam's staging tree is adopted into the install dir before downloading,
    and only cleared once the install is finished -- never discarded up front."""
    library, install_dir = steam
    staged = library.steamapps / "downloading" / "1771300"
    staged.mkdir(parents=True)
    (staged / "big.pak").write_bytes(b"x" * 2_000_000)
    _stub_download(monkeypatch)
    _stub_steamcmd(monkeypatch, returncode=8)

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
    _stub_steamcmd(monkeypatch, returncode=8)
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
    assert "--skip-steamcmd" in result.stdout


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

    assert cli.main([*ARGV, "--skip-steamcmd"]) == 0
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

    assert cli.main([*ARGV, "--skip-steamcmd"]) == 1
    assert recognize.read_app_state(manifest)["installdir"] == "KingdomComeDeliverance2"
