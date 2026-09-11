"""End-to-end-ish tests for the CLI's decision logic.

The bug that motivated all of this lived here, not in the manifest writer:
steamcmd died instantly having done nothing, and main() still wrote
StateFlags=4, printed "launch Steam and confirm Play works" and returned 0.
These tests pin the fail-closed behaviour.
"""

import logging
import subprocess
import sys

import pytest

from steam_installer import appinfo, cli, depotdl, deps, recognize, runlog, vdf
from steam_installer.library import SteamLibrary


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "LOG_DIR", tmp_path / "state")
    yield
    logger = logging.getLogger(runlog.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def steam(tmp_path, monkeypatch):
    """A Steam tree with KCD2 downloaded but its manifest not yet finished."""
    root = tmp_path / "Steam"
    library = SteamLibrary(root)
    install_dir = library.common / "KingdomComeDeliverance2"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1999516201078544527.manifest").write_bytes(b"x")
    (install_dir / "game.pak").write_bytes(b"x" * 1000)
    library.steamapps.mkdir(parents=True, exist_ok=True)
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps(
            "AppState",
            {
                "appid": "1771300",
                "StateFlags": "1026",
                "buildid": "23914554",
                "BytesToDownload": "92009052960",
                "BytesDownloaded": "22129058224",
            },
        )
    )

    monkeypatch.setattr(cli, "find_steam_root", lambda: root)
    monkeypatch.setattr(cli, "list_libraries", lambda r: [library])
    monkeypatch.setattr(cli, "pick_install_target", lambda libs, d: install_dir)
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        appinfo,
        "get_metadata",
        lambda appid: appinfo.AppMetadata(appid, "KCD2", "KingdomComeDeliverance2"),
    )
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan({"1771303"}, {"228989"}),
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda appid: "23914554")
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [])
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [])
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    # Prompting is tty-gated now, and pytest's stdin is not a tty.
    monkeypatch.setattr(cli, "_is_interactive", lambda args: True)
    return library, install_dir


ARGV = ["--appid", "1771300", "--username", "u", "--language", "english"]


def _stub_download(monkeypatch, returncode=0):
    monkeypatch.setattr(depotdl, "download", lambda **kw: returncode)


def _stub_steamcmd(monkeypatch, returncode, crashed=False):
    monkeypatch.setattr(
        recognize,
        "run_steamcmd_validate",
        lambda appid, username, logger: recognize.ValidateResult(
            completed=returncode == 0,
            crashed_on_install_script=crashed,
            returncode=returncode,
        ),
    )


def test_dead_steamcmd_run_still_finishes_when_content_is_present(steam, monkeypatch):
    """steamcmd failing is survivable -- the content is what matters -- but the
    manifest must come out consistent, not merely flagged installed."""
    library, install_dir = steam
    _stub_download(monkeypatch)
    _stub_steamcmd(monkeypatch, returncode=8)

    assert cli.main(ARGV) == 0

    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "4"
    assert app_state["BytesDownloaded"] == app_state["BytesToDownload"]
    assert recognize.download_counters_settled(app_state)


def test_refuses_when_a_required_depot_never_downloaded(steam, monkeypatch):
    """The exact fail-open case: nothing was really downloaded, so declaring the
    app installed would be a fabricated success."""
    library, install_dir = steam
    _stub_download(monkeypatch)
    _stub_steamcmd(monkeypatch, returncode=8)
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan({"1771303", "9999999"}, set()),
    )

    assert cli.main(ARGV) == 1

    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "1026"


def test_refuses_when_depotdownloader_fails(steam, monkeypatch):
    library, _ = steam
    _stub_download(monkeypatch, returncode=1)
    _stub_steamcmd(monkeypatch, returncode=0)

    assert cli.main(ARGV) == 1
    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "1026"


def test_declining_to_close_steam_aborts_before_downloading(steam, monkeypatch):
    """Steam owns the manifest while it runs. The tool offers to close it, but a
    "no" must stop the run rather than download for an hour and lose the write."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [4242])
    monkeypatch.setattr(
        "builtins.input", lambda *a: "n" if "Steam is running" in a[0] else "y"
    )
    called = []
    monkeypatch.setattr(depotdl, "download", lambda **kw: called.append(1) or 0)

    assert cli.main(ARGV) == 1
    assert called == []


def test_clean_steamcmd_run_short_circuits(steam, monkeypatch):
    """If steamcmd genuinely finished the job, don't hand-patch anything."""
    library, install_dir = steam
    _stub_download(monkeypatch)

    def fake_validate(appid, username, logger):
        (library.steamapps / "appmanifest_1771300.acf").write_text(
            vdf.dumps(
                "AppState",
                {
                    "StateFlags": "4",
                    "installdir": "KingdomComeDeliverance2",
                    "InstalledDepots": {"1771303": {"manifest": "1"}},
                    "BytesToDownload": "1",
                    "BytesDownloaded": "1",
                },
            )
        )
        return recognize.ValidateResult(True, False, 0)

    monkeypatch.setattr(recognize, "run_steamcmd_validate", fake_validate)
    called = []
    monkeypatch.setattr(
        recognize,
        "finish_manifest_manually",
        lambda **kw: called.append(1),
    )

    assert cli.main(ARGV) == 0
    assert called == []


def test_a_complete_install_after_a_failed_steamcmd_is_not_credited_to_it(
    steam, monkeypatch, capsys
):
    """A valid manifest does not mean steamcmd is why it is valid.

    steamcmd can fail to even log in while the install was already complete on
    arrival. Reporting that as "finished cleanly" credits a step that did
    nothing and hides a real authentication failure, so the non-zero exit has
    to say so out loud.
    """
    library, _ = steam
    _stub_download(monkeypatch)

    def fake_validate(appid, username, logger):
        (library.steamapps / "appmanifest_1771300.acf").write_text(
            vdf.dumps(
                "AppState",
                {
                    "StateFlags": "4",
                    "installdir": "KingdomComeDeliverance2",
                    "InstalledDepots": {"1771303": {"manifest": "1"}},
                    "BytesToDownload": "1",
                    "BytesDownloaded": "1",
                },
            )
        )
        return recognize.ValidateResult(True, False, 5)

    monkeypatch.setattr(recognize, "run_steamcmd_validate", fake_validate)
    called = []
    monkeypatch.setattr(
        recognize, "finish_manifest_manually", lambda **kw: called.append(1)
    )

    assert cli.main(ARGV) == 0
    out = capsys.readouterr().out
    assert "steamcmd exited 5" in out
    assert "finished cleanly" not in out
    assert called == []


def test_user_declining_confirmation_aborts(steam, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    called = []
    monkeypatch.setattr(depotdl, "download", lambda **kw: called.append(1) or 0)
    assert cli.main(ARGV) == 1
    assert called == []


def test_unhandled_error_returns_nonzero_and_names_the_log(steam, monkeypatch, capsys):
    def boom(**kwargs):
        raise RuntimeError("depotdownloader exploded")

    monkeypatch.setattr(depotdl, "download", boom)

    assert cli.main(ARGV) == 1
    assert "Run log" in capsys.readouterr().out


def test_requires_a_name_or_appid():
    with pytest.raises(SystemExit):
        cli.main(["--username", "u"])


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
