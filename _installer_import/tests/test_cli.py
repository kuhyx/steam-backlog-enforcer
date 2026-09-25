"""End-to-end-ish tests for the CLI's decision logic.

The bug that motivated all of this lived here, not in the manifest writer:
steamcmd died instantly having done nothing, and main() still wrote
StateFlags=4, printed "launch Steam and confirm Play works" and returned 0.
These tests pin the fail-closed behaviour.
"""

import pytest
from steam_installer import (
    appinfo,
    cli,
    depotdl,
    manifest_write,
    recognize,
    steamcmd_validate,
    vdf,
)

from _cli_helpers import ARGV, _stub_download, _stub_steamcmd

pytestmark = pytest.mark.usefixtures("cli_logs")


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
        return steamcmd_validate.ValidateResult(True, False, 0)

    monkeypatch.setattr(steamcmd_validate, "run_steamcmd_validate", fake_validate)
    called = []
    monkeypatch.setattr(
        manifest_write,
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
        return steamcmd_validate.ValidateResult(True, False, 5)

    monkeypatch.setattr(steamcmd_validate, "run_steamcmd_validate", fake_validate)
    called = []
    monkeypatch.setattr(
        manifest_write, "finish_manifest_manually", lambda **kw: called.append(1)
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
