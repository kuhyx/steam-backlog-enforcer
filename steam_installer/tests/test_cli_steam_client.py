"""The CLI and the Steam client: closed around an install, reopened after."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import appinfo, cli, depotdl, ghost, recognize

if TYPE_CHECKING:
    import logging


def _installable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        appinfo, "get_depot_plan", lambda a, language: appinfo.DepotPlan(set(), set())
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda a: "1")
    monkeypatch.setattr(depotdl, "download", lambda *a, **kw: 1)


@pytest.mark.usefixtures("cli_steam")
def test_declining_the_shutdown_prompt_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declining the shutdown prompt stops the run."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(cli, "_is_interactive", lambda args: True)
    monkeypatch.setattr(
        "builtins.input", lambda *a: "n" if "Steam is running" in a[0] else "y"
    )
    monkeypatch.setattr(
        depotdl, "download", lambda *a, **kw: pytest.fail("must not download")
    )

    assert cli.main(["284160", "--username", "u", "--language", "english"]) == 1


@pytest.mark.usefixtures("cli_steam")
def test_steam_is_closed_and_reopened_around_the_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It was running before, so it is running after -- whatever the outcome."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(ghost.recognize, "steam_client_pids", lambda: [42])
    events = []

    def stop(_logger: object) -> bool:
        events.append("stop")
        return True

    monkeypatch.setattr(cli.flow.steamctl, "stop", stop)
    monkeypatch.setattr(
        cli.flow.steamctl, "start", lambda logger: events.append("start")
    )
    _installable(monkeypatch)

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
    assert events == ["stop", "start"]


@pytest.mark.usefixtures("cli_steam")
def test_a_steam_that_refuses_to_exit_aborts_the_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Never escalate to a signal: a hung client is the user's to deal with."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])

    def refuse(_logger: logging.Logger) -> Never:
        msg = "Steam is still running after 60s"
        raise cli.flow.steamctl.SteamStillRunningError(msg)

    monkeypatch.setattr(cli.flow.steamctl, "stop", refuse)
    monkeypatch.setattr(
        depotdl, "download", lambda *a, **kw: pytest.fail("must not download")
    )

    assert cli.main(["--yes", "284160", "--username", "u"]) == 1
    assert "still running" in capsys.readouterr().out


@pytest.mark.usefixtures("cli_steam")
def test_accepting_the_shutdown_prompt_closes_and_reopens_steam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interactive path: asked, answered yes, Steam cycled around the run."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(cli, "_is_interactive", lambda args: True)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    events = []

    def stop(_logger: object) -> bool:
        events.append("stop")
        return True

    monkeypatch.setattr(cli.flow.steamctl, "stop", stop)
    monkeypatch.setattr(
        cli.flow.steamctl, "start", lambda logger: events.append("start")
    )
    _installable(monkeypatch)

    assert cli.main(["284160", "--username", "u", "--language", "english"]) == 1
    assert events == ["stop", "start"]
