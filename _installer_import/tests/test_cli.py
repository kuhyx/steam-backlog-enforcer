"""End-to-end-ish tests for the CLI's decision logic.

The bug that motivated all of this lived here, not in the manifest writer:
a step died instantly having done nothing, and main() still wrote
StateFlags=4, printed "launch Steam and confirm Play works" and returned 0.
These tests pin the fail-closed behaviour.
"""

import pytest
from steam_installer import (
    appinfo,
    cli,
    depotdl,
    recognize,
)

from _cli_helpers import ARGV, _stub_download

pytestmark = pytest.mark.usefixtures("cli_logs")


def test_downloaded_content_finishes_the_manifest(steam, monkeypatch):
    """The content is what matters, and the manifest must come out consistent,
    not merely flagged installed."""
    library, install_dir = steam
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0

    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "4"
    for key in ("BytesToDownload", "BytesDownloaded", "BytesToStage", "BytesStaged"):
        assert app_state[key] == "0", key
    assert recognize.download_counters_settled(app_state)


def test_refuses_when_a_required_depot_never_downloaded(steam, monkeypatch):
    """The exact fail-open case: nothing was really downloaded, so declaring the
    app installed would be a fabricated success."""
    library, install_dir = steam
    _stub_download(monkeypatch)
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
