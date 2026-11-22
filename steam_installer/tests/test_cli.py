"""End-to-end-ish tests for the CLI's decision logic.

The bug that motivated all of this lived here, not in the manifest writer:
a step died instantly having done nothing, and main() still wrote
StateFlags=4, printed "launch Steam and confirm Play works" and returned 0.
These tests pin the fail-closed behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import (
    appinfo,
    cli,
    depotdl,
    recognize,
)
from steam_installer.tests._cli_helpers import ARGV, _stub_download

if TYPE_CHECKING:
    from pathlib import Path

    from steam_installer.library import SteamLibrary

pytestmark = pytest.mark.usefixtures("cli_logs")


def test_downloaded_content_finishes_the_manifest(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The content is what matters, and the manifest must come out consistent,
    not merely flagged installed."""
    library, _install_dir = steam
    _stub_download(monkeypatch)

    assert cli.main(ARGV) == 0

    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "4"
    for key in ("BytesToDownload", "BytesDownloaded", "BytesToStage", "BytesStaged"):
        assert app_state[key] == "0", key
    assert recognize.download_counters_settled(app_state)


def test_refuses_when_a_required_depot_never_downloaded(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact fail-open case: nothing was really downloaded, so declaring the
    app installed would be a fabricated success."""
    library, _install_dir = steam
    _stub_download(monkeypatch)
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan({"1771303", "9999999"}, set()),
    )

    assert cli.main(ARGV) == 1

    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "1026"


def test_refuses_when_depotdownloader_fails(
    steam: tuple[SteamLibrary, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuses when depotdownloader fails."""
    library, _ = steam
    _stub_download(monkeypatch, returncode=1)

    assert cli.main(ARGV) == 1
    app_state = recognize.read_app_state(library.steamapps / "appmanifest_1771300.acf")
    assert app_state["StateFlags"] == "1026"


@pytest.mark.usefixtures("steam")
def test_declining_to_close_steam_aborts_before_downloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steam owns the manifest while it runs. The tool offers to close it, but a
    "no" must stop the run rather than download for an hour and lose the write."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [4242])
    monkeypatch.setattr(
        "builtins.input", lambda *a: "n" if "Steam is running" in a[0] else "y"
    )
    called = []

    def download(*_a: object, **_kw: object) -> int:
        called.append(1)
        return 0

    monkeypatch.setattr(depotdl, "download", download)

    assert cli.main(ARGV) == 1
    assert called == []


@pytest.mark.usefixtures("steam")
def test_user_declining_confirmation_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    """User declining confirmation aborts."""
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    called = []

    def download(*_a: object, **_kw: object) -> int:
        called.append(1)
        return 0

    monkeypatch.setattr(depotdl, "download", download)
    assert cli.main(ARGV) == 1
    assert called == []


@pytest.mark.usefixtures("steam")
def test_unhandled_error_returns_nonzero_and_names_the_log(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unhandled error returns nonzero and names the log."""

    def boom(*_args: object, **_kwargs: object) -> Never:
        msg = "depotdownloader exploded"
        raise RuntimeError(msg)

    monkeypatch.setattr(depotdl, "download", boom)

    assert cli.main(ARGV) == 1
    assert "Run log" in capsys.readouterr().out


@pytest.mark.usefixtures("steam")
@pytest.mark.parametrize("error", [AttributeError, KeyError, ZeroDivisionError])
def test_any_crash_is_logged_with_the_log_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: type[Exception],
) -> None:
    """A bug outside the expected errors is still logged, not left to a traceback."""

    def boom(*_args: object, **_kwargs: object) -> Never:
        msg = "bug"
        raise error(msg)

    monkeypatch.setattr(depotdl, "download", boom)

    assert cli.main(ARGV) == 1
    assert "Run log (send this)" in capsys.readouterr().out


@pytest.mark.usefixtures("steam")
def test_ctrl_c_still_interrupts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl c still interrupts."""

    def boom(*_args: object, **_kwargs: object) -> Never:
        raise KeyboardInterrupt

    monkeypatch.setattr(depotdl, "download", boom)

    with pytest.raises(KeyboardInterrupt):
        cli.main(ARGV)


def test_requires_a_name_or_appid() -> None:
    """Requires a name or appid."""
    with pytest.raises(SystemExit):
        cli.main(["--username", "u"])
