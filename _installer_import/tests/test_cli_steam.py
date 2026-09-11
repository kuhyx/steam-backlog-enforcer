"""What the CLI does around a real install: ghosts, usernames, the Steam client.

Split from test_cli_modes.py to keep both files under the repo's 250-line cap.
"""

import pytest

from steam_installer import appinfo, cli, config, depotdl, ghost, recognize
from tests.conftest import GHOST_ACF


def test_a_cold_ghost_blocks_an_install_and_names_the_fix(cli_steam, capsys):
    """Installing over a fabricated manifest is how Steam was tricked into
    re-downloading in the first place; stop and say what to run."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
    assert "./run.sh --repair-ghosts" in capsys.readouterr().out


def test_a_warm_ghost_does_not_block_an_install(cli_steam, monkeypatch):
    """Staged bytes are the whole reason to run this tool, not a blocker."""
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)
    staged = cli_steam.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 4096)
    reached = []
    monkeypatch.setattr(depotdl, "download", lambda **kw: reached.append(1) or 1)
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, l: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")

    cli.main(["--yes", "284160", "--username", "u"])

    assert reached == [1]


def test_repair_ghosts_clears_a_cold_ghost(cli_steam, capsys):
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)

    assert cli.main(["--repair-ghosts"]) == 0

    assert not (cli_steam.steamapps / "appmanifest_284160.acf").exists()
    assert "Ghost: appid 284160" in capsys.readouterr().out


def test_repair_ghosts_refuses_to_discard_a_warm_ghosts_download(cli_steam, capsys):
    (cli_steam.steamapps / "appmanifest_284160.acf").write_text(GHOST_ACF)
    staged = cli_steam.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 4096)

    assert cli.main(["--repair-ghosts"]) == 0

    assert (cli_steam.steamapps / "appmanifest_284160.acf").exists()
    assert (staged / "part.pak").exists()
    assert "nothing is deleted" in capsys.readouterr().out


def test_repair_ghosts_says_so_when_there_is_nothing_to_do(cli_steam, capsys):
    assert cli.main(["--repair-ghosts"]) == 0
    assert "No ghost installs found" in capsys.readouterr().out


def test_repair_ghosts_needs_no_target(cli_steam):
    """It is the one mode that runs without naming a game."""
    assert cli.main(["--repair-ghosts"]) == 0


def test_a_saved_username_removes_the_need_for_the_flag(cli_steam, monkeypatch):
    config.save_username("saved-user")
    seen = {}
    monkeypatch.setattr(
        depotdl,
        "download",
        lambda **kw: seen.setdefault("username", kw["username"]) or 1,
    )
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, l: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")

    cli.main(["--yes", "284160"])

    assert seen["username"] == "saved-user"


def test_no_username_anywhere_fails_with_an_explanation(cli_steam, capsys):
    assert cli.main(["--yes", "284160"]) == 1
    assert "No Steam username available" in capsys.readouterr().out


def test_a_non_interactive_run_without_yes_does_not_start_a_download(cli_steam, capsys):
    """A piped invocation never asked for a 50 GB download; refuse rather than
    assume."""
    assert cli.main(["284160", "--username", "u"]) == 1
    assert "use --yes" in capsys.readouterr().out


def test_language_defaults_to_english_when_not_interactive(cli_steam, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda a, language: (
            seen.setdefault("language", language) or appinfo.DepotPlan(set(), set())
        ),
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")
    monkeypatch.setattr(depotdl, "download", lambda **kw: 1)

    cli.main(["--yes", "284160", "--username", "u"])

    assert seen["language"] == "english"


def test_nothing_to_do_at_all_is_a_usage_error():
    with pytest.raises(SystemExit):
        cli.main(["--username", "u"])


def test_a_ghost_for_a_different_app_does_not_block_this_one(cli_steam, monkeypatch):
    (cli_steam.steamapps / "appmanifest_999.acf").write_text(
        GHOST_ACF.replace('"appid"\t\t"284160"', '"appid"\t\t"999"')
    )
    monkeypatch.setattr(depotdl, "download", lambda **kw: 1)
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, l: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1


def _installable(monkeypatch, library):
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, l: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")
    monkeypatch.setattr(depotdl, "download", lambda **kw: 1)


def test_declining_the_shutdown_prompt_stops_the_run(cli_steam, monkeypatch):
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(cli, "_is_interactive", lambda args: True)
    monkeypatch.setattr(
        "builtins.input", lambda *a: "n" if "Steam is running" in a[0] else "y"
    )
    monkeypatch.setattr(
        depotdl, "download", lambda **kw: pytest.fail("must not download")
    )

    assert cli.main(["284160", "--username", "u", "--language", "english"]) == 1


def test_steam_is_closed_and_reopened_around_the_install(cli_steam, monkeypatch):
    """It was running before, so it is running after -- whatever the outcome."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(ghost.recognize, "steam_client_pids", lambda: [42])
    events = []
    monkeypatch.setattr(
        cli.flow.steamctl, "stop", lambda logger: events.append("stop") or True
    )
    monkeypatch.setattr(
        cli.flow.steamctl, "start", lambda logger: events.append("start")
    )
    _installable(monkeypatch, cli_steam)

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
    assert events == ["stop", "start"]


def test_a_steam_that_refuses_to_exit_aborts_the_run(cli_steam, monkeypatch, capsys):
    """Never escalate to a signal: a hung client is the user's to deal with."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])

    def refuse(logger):
        raise cli.flow.steamctl.SteamStillRunning("Steam is still running after 60s")

    monkeypatch.setattr(cli.flow.steamctl, "stop", refuse)
    monkeypatch.setattr(
        depotdl, "download", lambda **kw: pytest.fail("must not download")
    )

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
    assert "still running" in capsys.readouterr().out


def test_accepting_the_shutdown_prompt_closes_and_reopens_steam(cli_steam, monkeypatch):
    """The interactive path: asked, answered yes, Steam cycled around the run."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(cli, "_is_interactive", lambda args: True)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    events = []
    monkeypatch.setattr(
        cli.flow.steamctl, "stop", lambda logger: events.append("stop") or True
    )
    monkeypatch.setattr(
        cli.flow.steamctl, "start", lambda logger: events.append("start")
    )
    _installable(monkeypatch, cli_steam)

    assert cli.main(["284160", "--username", "u", "--language", "english"]) == 1
    assert events == ["stop", "start"]
