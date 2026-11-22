"""What the CLI does around a real install: ghosts, usernames, the Steam client.

Split from test_cli_modes.py to keep both files under the repo's 250-line cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_installer import appinfo, cli, config, depotdl
from steam_installer.tests._acf_helpers import GHOST_ACF

if TYPE_CHECKING:
    from steam_installer.library import SteamLibrary


def test_a_cold_ghost_blocks_an_install_and_names_the_fix(
    cli_steam: SteamLibrary, capsys: pytest.CaptureFixture[str]
) -> None:
    """Installing over a fabricated manifest is how Steam was tricked into
    re-downloading in the first place; stop and say what to run."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
    assert "steam_installer/run.sh --repair-ghosts" in capsys.readouterr().out


def test_a_warm_ghost_does_not_block_an_install(
    cli_steam: SteamLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Staged bytes are the whole reason to run this tool, not a blocker."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)
    staged = cli_steam.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 4096)
    reached = []

    def download(_appid: int, _pull: object, _logger: object) -> int:
        reached.append(1)
        return 1

    monkeypatch.setattr(depotdl, "download", download)
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, language: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")

    cli.main(["--yes", "284160", "--username", "u"])

    assert reached == [1]


def test_repair_ghosts_clears_a_cold_ghost(
    cli_steam: SteamLibrary, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repair ghosts clears a cold ghost."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)

    assert cli.main(["--repair-ghosts"]) == 0

    assert not (cli_steam.steamapps / "appmanifest_284160.acf").exists()
    assert "Ghost: appid 284160" in capsys.readouterr().out


def test_repair_ghosts_refuses_to_discard_a_warm_ghosts_download(
    cli_steam: SteamLibrary, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repair ghosts refuses to discard a warm ghosts download."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)
    staged = cli_steam.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 4096)

    assert cli.main(["--repair-ghosts"]) == 0

    assert (cli_steam.steamapps / "appmanifest_284160.acf").exists()
    assert (staged / "part.pak").exists()
    assert "nothing is deleted" in capsys.readouterr().out


@pytest.mark.usefixtures("cli_steam")
def test_repair_ghosts_says_so_when_there_is_nothing_to_do(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Repair ghosts says so when there is nothing to do."""
    assert cli.main(["--repair-ghosts"]) == 0
    assert "No ghost installs found" in capsys.readouterr().out


@pytest.mark.usefixtures("cli_steam")
def test_repair_ghosts_needs_no_target() -> None:
    """It is the one mode that runs without naming a game."""
    assert cli.main(["--repair-ghosts"]) == 0


@pytest.mark.usefixtures("cli_steam")
def test_a_saved_username_removes_the_need_for_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saved username removes the need for the flag."""
    config.save_username("saved-user")
    seen = {}
    monkeypatch.setattr(
        depotdl,
        "download",
        lambda appid, pull, logger: seen.setdefault("username", pull.username) and 1,
    )
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, language: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")

    cli.main(["--yes", "284160"])

    assert seen["username"] == "saved-user"


@pytest.mark.usefixtures("cli_steam")
def test_no_username_anywhere_fails_with_an_explanation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No username anywhere fails with an explanation."""
    assert cli.main(["--yes", "284160"]) == 1
    assert "No Steam username available" in capsys.readouterr().out


@pytest.mark.usefixtures("cli_steam")
def test_a_non_interactive_run_without_yes_does_not_start_a_download(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A piped invocation never asked for a 50 GB download; refuse rather than
    assume."""
    assert cli.main(["284160", "--username", "u"]) == 1
    assert "use --yes" in capsys.readouterr().out


@pytest.mark.usefixtures("cli_steam")
def test_language_defaults_to_english_when_not_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Language defaults to english when not interactive."""
    seen = {}

    def get_depot_plan(_appid: int, language: str) -> appinfo.DepotPlan:
        seen["language"] = language
        return appinfo.DepotPlan(set(), set())

    monkeypatch.setattr(appinfo, "get_depot_plan", get_depot_plan)
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")
    monkeypatch.setattr(depotdl, "download", lambda appid, pull, logger: 1)

    cli.main(["--yes", "284160", "--username", "u"])

    assert seen["language"] == "english"


def test_nothing_to_do_at_all_is_a_usage_error() -> None:
    """Nothing to do at all is a usage error."""
    with pytest.raises(SystemExit):
        cli.main(["--username", "u"])


def test_a_ghost_for_a_different_app_does_not_block_this_one(
    cli_steam: SteamLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ghost for a different app does not block this one."""
    (cli_steam.steamapps / "appmanifest_999.acf").write_text(
        GHOST_ACF.replace('"appid"\t\t"284160"', '"appid"\t\t"999"')
    )
    monkeypatch.setattr(depotdl, "download", lambda *a, **kw: 1)
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, language: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
