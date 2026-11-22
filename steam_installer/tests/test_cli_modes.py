"""The CLI front door: turning one free-form argument into a resolved target.

test_cli.py covers the download/recognize decision logic; test_cli_steam.py
covers ghosts, usernames and the Steam client. This file covers detection and
the modes that deliberately change nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import cli, deps, target
from steam_installer.tests._acf_helpers import GHOST_ACF

if TYPE_CHECKING:
    from steam_installer.library import SteamLibrary


@pytest.mark.usefixtures("cli_steam")
def test_a_bare_appid_resolves_and_reports_without_changing_anything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bare appid resolves and reports without changing anything."""
    assert cli.main(["--dry-run", "284160"]) == 0
    out = capsys.readouterr().out
    assert "BeamNG.drive (appid 284160, matched by appid)" in out
    assert "nothing was changed" in out


@pytest.mark.usefixtures("cli_steam")
def test_a_steam_url_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    """A steam url resolves."""
    assert cli.main(["--dry-run", "https://steamcommunity.com/app/284160/guides/"]) == 0
    assert "matched by url" in capsys.readouterr().out


def test_a_dry_run_reports_staged_bytes_it_would_adopt(
    cli_steam: SteamLibrary, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run reports staged bytes it would adopt."""
    staged = cli_steam.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 4096)

    assert cli.main(["--dry-run", "284160"]) == 0
    assert "would be adopted, not re-downloaded" in capsys.readouterr().out


def test_a_dry_run_names_a_ghost_manifest(
    cli_steam: SteamLibrary, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run names a ghost manifest."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)

    assert cli.main(["--dry-run", "284160"]) == 0
    assert "GHOST manifest" in capsys.readouterr().out


@pytest.mark.usefixtures("cli_steam")
def test_an_ambiguous_name_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambiguous name exits two."""

    def boom(_text: str | None, _appid: int | None, **_kw: bool) -> Never:
        msg = "Ambiguous name"
        raise target.TargetError(msg)

    monkeypatch.setattr(target, "resolve_target", boom)
    assert cli.main(["--dry-run", "witcher"]) == 2


@pytest.mark.usefixtures("cli_steam")
def test_a_missing_dependency_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing dependency exits one."""
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    assert cli.main(["--dry-run", "284160"]) == 1
    assert "depotdownloader" in capsys.readouterr().out
