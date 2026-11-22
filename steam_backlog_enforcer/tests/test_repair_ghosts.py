"""Tests for ``repair-ghosts``: CLI command, job, catalog and POST-time friction."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _command_catalog, _web_jobs
from steam_backlog_enforcer._fast_install_cmd import build_repair_ghosts_cmd
from steam_backlog_enforcer._friction import expected_phrase
from steam_backlog_enforcer._prompter import PromptAbortedError, use_prompter
from steam_backlog_enforcer._web_errors import STATUS_BY_CODE, ApiError
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs import _registry
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS
from steam_backlog_enforcer.main import COMMANDS
from steam_backlog_enforcer.main.repair_ghosts import cmd_repair_ghosts
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter
from steam_backlog_enforcer.tests._web_request import make_request

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer.main.repair_ghosts"
TGT = "steam_backlog_enforcer.main._install_target"
PHRASE = "delete ghost manifests"


@pytest.fixture(name="env")
def _env() -> Iterator[dict[str, MagicMock]]:
    """No game running, an installer present, the subprocess mocked."""
    with (
        patch(f"{PKG}.game_is_running", return_value=False) as running,
        patch(f"{PKG}.installer_path", return_value=MagicMock()),
        patch(f"{PKG}.build_repair_ghosts_cmd", return_value=["inst"]) as build,
        patch(f"{TGT}.subprocess.run") as run,
        patch(f"{TGT}._echo") as echo,
    ):
        run.return_value = MagicMock(returncode=0, stdout="No ghost installs found.\n")
        yield {"running": running, "run": run, "build": build, "echo": echo}


def _run(phrases: tuple[bool, ...] = (True,)) -> FakePrompter:
    prompter = FakePrompter(phrases=phrases)
    with use_prompter(prompter):
        cmd_repair_ghosts(Config(), State())
    return prompter


class TestCommand:
    """``cmd_repair_ghosts``: guard, phrase, then the installer."""

    def test_runs_the_installer_and_relays_its_report(
        self, env: dict[str, MagicMock]
    ) -> None:
        """The right phrase runs ``--repair-ghosts`` and echoes every line."""
        prompter = _run()
        assert prompter.asked[0][1] == PHRASE
        env["run"].assert_called_once()
        assert env["run"].call_args.args[0] == ["inst"]
        env["echo"].assert_any_call("  No ghost installs found.")

    def test_game_running_refuses_before_the_phrase(
        self, env: dict[str, MagicMock]
    ) -> None:
        """A running game refuses with ``game_running``; nothing runs."""
        env["running"].return_value = True
        with pytest.raises(JobError) as exc:
            _run(phrases=())
        assert exc.value.code == "game_running"
        env["run"].assert_not_called()

    def test_wrong_phrase_aborts(self, env: dict[str, MagicMock]) -> None:
        """A wrong phrase aborts the job and never runs the installer."""
        with pytest.raises(PromptAbortedError):
            _run(phrases=(False,))
        env["run"].assert_not_called()

    def test_installer_failure_fails_the_job(self, env: dict[str, MagicMock]) -> None:
        """A non-zero installer exit is ``op_failed``."""
        env["run"].return_value = MagicMock(returncode=1, stdout="ERROR x\n")
        with pytest.raises(JobError) as exc:
            _run()
        assert exc.value.code == "op_failed"

    def test_missing_installer(self, env: dict[str, MagicMock]) -> None:
        """No installer in the checkout fails loudly before any subprocess."""
        with (
            patch(f"{PKG}.installer_path", return_value=None),
            pytest.raises(JobError),
        ):
            _run()
        env["run"].assert_not_called()


class TestWiring:
    """CLI, job, catalog, friction and error-code tables."""

    def test_argv(self, tmp_path: Path) -> None:
        """The installer gets ``--repair-ghosts`` and no AppID."""
        installer = tmp_path / "steam_installer" / "cli.py"
        with patch(
            "steam_backlog_enforcer._fast_install_cmd.desktop_user_cmd",
            side_effect=lambda cmd, _user: cmd,
        ):
            cmd = build_repair_ghosts_cmd(installer, None)
        assert cmd[-3:] == ["-m", "steam_installer.cli", "--repair-ghosts"]
        assert f"PYTHONPATH={tmp_path}" in cmd
        assert "--appid" not in cmd

    def test_tables(self) -> None:
        """One phrase, one 409 code, a CLI command, a job and a library card."""
        assert expected_phrase("repair-ghosts") == PHRASE
        assert STATUS_BY_CODE["game_running"] == HTTPStatus.CONFLICT
        assert COMMANDS["repair-ghosts"][1] is cmd_repair_ghosts
        assert JOB_FLAGS["repair-ghosts"].mutating
        assert "repair-ghosts" in _registry.HANDLERS
        assert _command_catalog.CATALOG["repair-ghosts"].category == "library"

    def test_job_handler_returns_the_assignment(
        self, env: dict[str, MagicMock]
    ) -> None:
        """The job runs the CLI command and reports the assignment."""
        with (
            use_prompter(FakePrompter(phrases=(True,))),
            patch.object(_registry.State, "load", return_value=State()),
            patch.object(_registry.Config, "load", return_value=Config()),
        ):
            data = _registry.HANDLERS["repair-ghosts"]({}, MagicMock(), MagicMock())
        env["run"].assert_called_once()
        assert data == {"current_app_id": None, "current_game_name": None}


_WEB = "steam_backlog_enforcer._web_jobs"


def _post(phrase: str | None, *, running: bool = False) -> tuple[object, MagicMock]:
    body: dict[str, object] = {"command": "repair-ghosts", "params": {}}
    if phrase is not None:
        body["confirm_phrase"] = phrase
    with (
        patch(f"{_WEB}.create_job", return_value="j1") as create,
        patch(f"{_WEB}.read_job", return_value={"id": "j1"}),
        patch(f"{_WEB}.game_is_running", return_value=running),
    ):
        try:
            reply: object = _web_jobs.create_job_view(make_request(body=body))
        except ApiError as exc:
            reply = exc
    return reply, create


class TestPostTimeFriction:
    """``POST /api/jobs`` refuses before a job exists."""

    @pytest.mark.parametrize("phrase", [None, "", "Delete ghost manifests"])
    def test_wrong_phrase_creates_no_job(self, phrase: str | None) -> None:
        """A missing or wrong phrase is ``wrong_phrase`` and no job."""
        reply, create = _post(phrase)
        assert isinstance(reply, ApiError)
        assert reply.code == "wrong_phrase"
        create.assert_not_called()

    def test_wrong_phrase_wins_over_a_running_game(self) -> None:
        """The phrase is checked first, so friction is provable mid-game."""
        reply, _ = _post("nope", running=True)
        assert isinstance(reply, ApiError)
        assert reply.code == "wrong_phrase"

    def test_game_running_creates_no_job(self) -> None:
        """The right phrase while a game runs is ``game_running`` (409)."""
        reply, create = _post(PHRASE, running=True)
        assert isinstance(reply, ApiError)
        assert (reply.code, reply.status) == ("game_running", HTTPStatus.CONFLICT)
        create.assert_not_called()

    def test_right_phrase_creates_the_job(self) -> None:
        """The right phrase with no game creates the job, phrase passed on."""
        reply, create = _post(f" {PHRASE} ")
        assert not isinstance(reply, ApiError)
        create.assert_called_once_with(
            "repair-ghosts", {}, confirm_phrase=f" {PHRASE} "
        )

    def test_other_commands_are_not_prechecked(self) -> None:
        """Commands outside the set keep their job-side check only."""
        with (
            patch(f"{_WEB}.create_job", return_value="j1") as create,
            patch(f"{_WEB}.read_job", return_value={"id": "j1"}),
            patch(f"{_WEB}.game_is_running", return_value=True),
        ):
            _web_jobs.create_job_view(
                make_request(body={"command": "uninstall", "params": {}})
            )
        create.assert_called_once()
