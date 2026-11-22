"""Tests for ``install`` with a target, a dry run and the Valve-Proton switch.

The locker stays intact: the target is resolved and checked by the enforcer
against the games allowed today (the assignment, manual picks and approved
exceptions), and the installer only ever gets the checked ``--appid``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._command_params import validate_params
from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs import _registry
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.main import cmd_install
from steam_backlog_enforcer.main._install_target import (
    install_candidates,
    resolve_target,
)
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer.main.install"
TGT = "steam_backlog_enforcer.main._install_target"
CANDIDATES = [(1, "Portal"), (2, "Portal 2"), (3, "Hades")]


def _state() -> State:
    return State(
        current_app_id=1,
        current_game_name="Portal",
        manual_picks=[{"app_id": 2, "game_name": "Portal 2"}],
    )


@pytest.fixture(name="env")
def _env() -> Iterator[dict[str, MagicMock]]:
    """Exceptions = {3: Hades}; nothing installed; no game running."""
    with (
        patch(f"{TGT}.get_approved_exception_ids", return_value=frozenset({3})),
        patch(
            f"{TGT}.load_owned_records",
            return_value=[{"app_id": 3, "name": "Hades"}],
        ),
        patch(f"{PKG}.is_game_fully_installed", return_value=False),
        patch(f"{PKG}.install_game", return_value=True) as install,
        patch(f"{PKG}.fast_install_failure", return_value=None),
        patch(f"{PKG}.game_is_running", return_value=False) as running,
        patch(f"{TGT}.subprocess.run") as run,
        patch(f"{TGT}.installer_path", return_value=MagicMock()),
        patch(f"{TGT}.build_cmd", return_value=["installer"]) as build,
        patch(f"{PKG}._echo"),
        patch(f"{TGT}._echo"),
    ):
        run.return_value = MagicMock(returncode=0, stdout="would install\n")
        yield {"install": install, "run": run, "build": build, "running": running}


class TestCandidates:
    """Allowed today = allowed_games plus approved exceptions."""

    def test_exception_is_a_candidate_with_its_owned_name(self) -> None:
        """An approved exception is offered under its owned-records name."""
        with (
            patch(f"{TGT}.get_approved_exception_ids", return_value=frozenset({3})),
            patch(
                f"{TGT}.load_owned_records",
                return_value=[{"app_id": 3, "name": "Hades"}, {"app_id": 9}],
            ),
        ):
            assert install_candidates(Config(steam_id="i"), _state()) == CANDIDATES

    def test_exception_without_records_gets_an_empty_name(self) -> None:
        """No owned records: the exception still counts, nameless."""
        with (
            patch(f"{TGT}.get_approved_exception_ids", return_value=frozenset({1, 5})),
            patch(f"{TGT}.load_owned_records", return_value=None),
        ):
            got = install_candidates(Config(steam_id="i"), _state())
        assert got == [(1, "Portal"), (2, "Portal 2"), (5, "")]


class TestResolveTarget:
    """AppID, URL and name all resolve inside the allowed set only."""

    def test_appid(self) -> None:
        """A bare allowed AppID resolves to itself."""
        assert resolve_target("2", CANDIDATES) == (2, "Portal 2")

    def test_url(self) -> None:
        """A store URL resolves through its ``app/<id>``."""
        url = "https://store.steampowered.com/app/3/Hades/"
        assert resolve_target(url, CANDIDATES) == (3, "Hades")

    @pytest.mark.parametrize(
        "text", ["999", "https://steamcommunity.com/app/999/guides/", "Doom"]
    )
    def test_not_allowed_is_refused(self, text: str) -> None:
        """Any game outside the allowed set is refused as ``locked``."""
        with pytest.raises(JobError) as exc:
            resolve_target(text, CANDIDATES)
        assert exc.value.code == "locked"

    def test_exact_name_wins(self) -> None:
        """A fully typed title does not install the sequel."""
        assert resolve_target("portal", CANDIDATES) == (1, "Portal")

    def test_unique_partial_name(self) -> None:
        """A unique partial name resolves without asking."""
        assert resolve_target("had", CANDIDATES) == (3, "Hades")

    def test_ambiguous_name_asks(self) -> None:
        """Several matches are offered as a choice, never guessed."""
        prompter = FakePrompter(choices=["2"])
        with use_prompter(prompter):
            assert resolve_target("Port", CANDIDATES) == (2, "Portal 2")
        assert prompter.asked[0][1] == ["1", "2"]


class TestInstallJob:
    """cmd_install with the web job's params."""

    def test_picker_offers_not_installed_exception(
        self, env: dict[str, MagicMock]
    ) -> None:
        """Todo 6ee260a4: the no-target picker includes approved exceptions."""
        prompter = FakePrompter(choices=["3"])
        with use_prompter(prompter):
            cmd_install(Config(steam_id="i"), _state())
        assert prompter.asked[0][1] == ["1", "2", "3"]
        assert env["install"].call_args.args[:2] == (3, "Hades")

    def test_disallowed_target_starts_nothing(self, env: dict[str, MagicMock]) -> None:
        """A refused target never reaches the installer."""
        with pytest.raises(JobError):
            cmd_install(Config(steam_id="i"), _state(), target="999")
        env["install"].assert_not_called()
        env["run"].assert_not_called()

    def test_allowed_target_installs(self, env: dict[str, MagicMock]) -> None:
        """An allowed target installs, Valve Proton passed through."""
        result = cmd_install(
            Config(steam_id="i"), _state(), target="Hades", valve_proton=True
        )
        assert env["install"].call_args.args[:2] == (3, "Hades")
        assert env["install"].call_args.kwargs["valve_proton"] is True
        assert result == {"app_id": 3, "dry_run": False, "fast_install_skipped": None}

    def test_game_running_is_reported(self, env: dict[str, MagicMock]) -> None:
        """The fast-install guard's refusal is in the result data for the UI."""
        env["running"].return_value = True
        result = cmd_install(Config(steam_id="i"), _state(), target="3")
        assert result is not None
        assert result["fast_install_skipped"] == "game_running"

    def test_dry_run_changes_nothing(self, env: dict[str, MagicMock]) -> None:
        """Dry run: only the installer's --dry-run, even with a game running."""
        env["running"].return_value = True
        result = cmd_install(
            Config(steam_id="i"), _state(), target="3", dry_run=True, valve_proton=True
        )
        env["install"].assert_not_called()
        assert env["build"].call_args.kwargs == {"valve_proton": True, "dry_run": True}
        assert env["build"].call_args.args[1] == 3
        assert result == {"app_id": 3, "dry_run": True, "fast_install_skipped": None}

    def test_failed_dry_run_fails_the_job(self, env: dict[str, MagicMock]) -> None:
        """A dry run the installer rejects is a failed job, not a success."""
        env["run"].return_value = MagicMock(returncode=1, stdout="ERROR x\n")
        with pytest.raises(JobError) as exc:
            cmd_install(Config(steam_id="i"), _state(), target="3", dry_run=True)
        assert exc.value.code == "op_failed"

    def test_dry_run_without_installer(self, env: dict[str, MagicMock]) -> None:
        """No installer in the checkout: the dry run fails loudly."""
        with (
            patch(f"{TGT}.installer_path", return_value=None),
            pytest.raises(JobError),
        ):
            cmd_install(Config(steam_id="i"), _state(), target="3", dry_run=True)
        env["run"].assert_not_called()


class TestInstallParamsAndHandler:
    """The web form's params reach cmd_install unchanged."""

    def test_install_params_are_optional(self) -> None:
        """target / dry_run / valve_proton are all optional."""
        assert validate_params("install", {}) == {"dry_run": 0, "valve_proton": 0}
        got = validate_params("install", {"target": " Hades ", "dry_run": 1})
        assert got == {"target": "Hades", "dry_run": 1, "valve_proton": 0}

    def test_handler_maps_params(self) -> None:
        """The job handler turns the flat params into cmd_install kwargs."""
        with (
            patch.object(_registry, "cmd_install", return_value={"app_id": 3}) as cmd,
            patch.object(_registry.State, "load", return_value=_state()),
            patch.object(_registry.Config, "load", return_value=Config()),
        ):
            out = _registry.HANDLERS["install"](
                {"target": "3", "dry_run": 1, "valve_proton": 0},
                MagicMock(),
                MagicMock(),
            )
        assert out == {"app_id": 3}
        assert cmd.call_args.kwargs == {
            "target": "3",
            "dry_run": True,
            "valve_proton": False,
        }

    def test_handler_without_target(self) -> None:
        """No target: the picker path, and None data becomes the assignment."""
        with (
            patch.object(_registry, "cmd_install", return_value=None) as cmd,
            patch.object(_registry.State, "load", return_value=_state()),
            patch.object(_registry.Config, "load", return_value=Config()),
        ):
            out = _registry.HANDLERS["install"]({}, MagicMock(), MagicMock())
        assert cmd.call_args.kwargs["target"] is None
        assert out == {"current_app_id": 1, "current_game_name": "Portal"}
