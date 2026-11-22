"""The CLI front door: turning one free-form argument into a resolved target.

test_cli.py covers the download/recognize decision logic; test_cli_steam.py
covers ghosts, usernames and the Steam client. This file covers detection and
the modes that deliberately change nothing.
"""

from steam_installer import cli, deps, target
from tests.conftest import GHOST_ACF


def test_a_bare_appid_resolves_and_reports_without_changing_anything(cli_steam, capsys):
    assert cli.main(["--dry-run", "284160"]) == 0
    out = capsys.readouterr().out
    assert "BeamNG.drive (appid 284160, matched by appid)" in out
    assert "nothing was changed" in out


def test_a_steam_url_resolves(cli_steam, capsys):
    assert cli.main(["--dry-run", "https://steamcommunity.com/app/284160/guides/"]) == 0
    assert "matched by url" in capsys.readouterr().out


def test_a_dry_run_reports_staged_bytes_it_would_adopt(cli_steam, capsys):
    staged = cli_steam.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 4096)

    assert cli.main(["--dry-run", "284160"]) == 0
    assert "would be adopted, not re-downloaded" in capsys.readouterr().out


def test_a_dry_run_names_a_ghost_manifest(cli_steam, capsys):
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)

    assert cli.main(["--dry-run", "284160"]) == 0
    assert "GHOST manifest" in capsys.readouterr().out


def test_an_ambiguous_name_exits_two(cli_steam, monkeypatch):
    def boom(text, appid, *, interactive):
        raise target.TargetError("Ambiguous name")

    monkeypatch.setattr(target, "resolve_target", boom)
    assert cli.main(["--dry-run", "witcher"]) == 2


def test_a_missing_dependency_exits_one(cli_steam, monkeypatch, capsys):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    assert cli.main(["--dry-run", "284160"]) == 1
    assert "depotdownloader" in capsys.readouterr().out
