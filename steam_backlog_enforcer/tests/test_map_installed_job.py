"""``map-installed``: the apply job, its streaming and the tables."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _command_catalog
from steam_backlog_enforcer._command_params import PARAMS, InvalidParamsError
from steam_backlog_enforcer._fast_install_cmd import build_map_installed_cmd
from steam_backlog_enforcer._friction import expected_phrase
from steam_backlog_enforcer._prompter import PromptAbortedError, use_prompter
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs import _registry
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS
from steam_backlog_enforcer.main import COMMANDS
from steam_backlog_enforcer.main import map_installed as job
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer.main.map_installed"


def _proc(lines: str, code: int = 0) -> MagicMock:
    proc = MagicMock(returncode=code)
    proc.stdout = io.StringIO(lines)
    proc.wait.return_value = code
    proc.__enter__.return_value = proc
    return proc


@pytest.fixture(name="env")
def _env() -> Iterator[dict[str, MagicMock]]:
    """No game running, two games to map, an installer, Popen mocked."""
    with (
        patch(f"{PKG}.game_is_running", return_value=False) as running,
        patch(f"{PKG}.checked_appids", return_value=[10, 30]) as ids,
        patch(f"{PKG}.installer_path", return_value=MagicMock()),
        patch(f"{PKG}.build_map_installed_cmd", return_value=["inst"]) as build,
        patch(f"{PKG}.subprocess.Popen") as popen,
        patch(f"{PKG}._echo") as echo,
    ):
        popen.return_value = _proc("Compat tool for 10: mapped.\n")
        yield {
            "running": running,
            "ids": ids,
            "build": build,
            "popen": popen,
            "echo": echo,
        }


def _run(
    raw: str | None = "10,30", phrases: tuple[bool, ...] = (True,)
) -> FakePrompter:
    prompter = FakePrompter(phrases=phrases)
    with use_prompter(prompter):
        job.run_map_installed(raw)
    return prompter


class TestJob:
    """``run_map_installed``: guard, phrase, then the streamed installer."""

    def test_maps_the_checked_ids_and_streams_output(
        self, env: dict[str, MagicMock]
    ) -> None:
        """The phrase counts the ids; the installer gets exactly those ids."""
        prompter = _run()
        assert prompter.asked[0][1] == "map 2 games"
        env["ids"].assert_called_once_with("10,30")
        assert env["build"].call_args.args[2] == [10, 30]
        env["echo"].assert_any_call("  Compat tool for 10: mapped.")

    def test_game_running_refuses_first(self, env: dict[str, MagicMock]) -> None:
        """Closing Steam would kill the game: refuse before anything else."""
        env["running"].return_value = True
        with pytest.raises(JobError) as exc:
            _run(phrases=())
        assert exc.value.code == "game_running"
        env["popen"].assert_not_called()

    def test_wrong_phrase_aborts(self, env: dict[str, MagicMock]) -> None:
        """A wrong phrase never starts the installer."""
        with pytest.raises(PromptAbortedError):
            _run(phrases=(False,))
        env["popen"].assert_not_called()

    def test_bad_appids_fail_the_job(self, env: dict[str, MagicMock]) -> None:
        """Ids that stopped being valid since the POST are ``invalid_params``."""
        env["ids"].side_effect = InvalidParamsError("999 is not installed")
        with pytest.raises(JobError) as exc:
            _run()
        assert exc.value.code == "invalid_params"

    def test_installer_failure(self, env: dict[str, MagicMock]) -> None:
        """A non-zero exit is ``op_failed``."""
        env["popen"].return_value = _proc("ERROR\n", code=1)
        with pytest.raises(JobError) as exc:
            _run()
        assert exc.value.code == "op_failed"

    def test_missing_installer(self, env: dict[str, MagicMock]) -> None:
        """No installer in the checkout fails before any subprocess."""
        with patch(f"{PKG}.installer_path", return_value=None), pytest.raises(JobError):
            _run()
        env["popen"].assert_not_called()

    def test_cli_command_maps_every_changing_game(
        self, env: dict[str, MagicMock]
    ) -> None:
        """``./run.sh map-installed`` is the job with no list."""
        with use_prompter(FakePrompter(phrases=(True,))):
            job.cmd_map_installed(Config(), State())
        env["ids"].assert_called_once_with(None)

    def test_job_handler_passes_the_param(self, env: dict[str, MagicMock]) -> None:
        """The job handler hands ``appids`` through and reports the ids."""
        with use_prompter(FakePrompter(phrases=(True,))):
            data = _registry.HANDLERS["map-installed"](
                {"appids": "10,30"}, MagicMock(), MagicMock()
            )
        env["ids"].assert_called_once_with("10,30")
        assert data == {"app_ids": [10, 30]}


class _FiringTimer:
    """A ``threading.Timer`` whose deadline has already passed."""

    def __init__(self, _seconds: float, fn: Callable[[], None]) -> None:
        self.fn = fn
        self.daemon = False

    def start(self) -> None:
        """Fire at once: the deadline has already passed."""
        self.fn()

    def cancel(self) -> None:
        """Nothing left to cancel."""


def test_stream_times_out_and_kills() -> None:
    """A run past its deadline is killed and reported as a failure."""
    proc = _proc("")
    proc.wait.return_value = -9
    with (
        patch(f"{PKG}.subprocess.Popen", return_value=proc),
        patch(f"{PKG}.threading.Timer", _FiringTimer),
        patch(f"{PKG}._echo") as echo,
    ):
        assert job.stream_installer(["x"], timeout=1) == -9
    proc.kill.assert_called_once()
    echo.assert_any_call("  Killed after 1 s.")


def test_stream_killed_with_a_zero_exit_still_fails() -> None:
    """A kill that somehow reports 0 is still a failure."""
    proc = _proc("")
    proc.wait.return_value = 0
    with (
        patch(f"{PKG}.subprocess.Popen", return_value=proc),
        patch(f"{PKG}.threading.Timer", _FiringTimer),
        patch(f"{PKG}._echo"),
    ):
        assert job.stream_installer(["x"], timeout=1) == 1


def test_stream_returns_the_exit_code() -> None:
    """No timeout: the installer's own exit code."""
    proc = _proc("a\n", code=3)
    with patch(f"{PKG}.subprocess.Popen", return_value=proc), patch(f"{PKG}._echo"):
        assert job.stream_installer(["x"], timeout=60) == 3


def test_argv(tmp_path: Path) -> None:
    """``--map-installed --apply --yes --appids`` with the checked ids."""
    installer = tmp_path / "steam_installer" / "cli.py"
    with patch(
        "steam_backlog_enforcer._fast_install_cmd.desktop_user_cmd",
        side_effect=lambda cmd, _user: cmd,
    ):
        cmd = build_map_installed_cmd(installer, None, [10, 30])
    assert cmd[-6:] == [
        "steam_installer.cli",
        "--map-installed",
        "--apply",
        "--yes",
        "--appids",
        "10,30",
    ]
    assert f"PYTHONPATH={tmp_path}" in cmd


def test_tables() -> None:
    """Phrase, CLI command, job, catalog entry and the optional param."""
    assert expected_phrase("map-installed", appid_count=3) == "map 3 games"
    assert COMMANDS["map-installed"][1] is job.cmd_map_installed
    assert JOB_FLAGS["map-installed"].mutating
    assert _command_catalog.CATALOG["map-installed"].category == "library"
    (spec,) = PARAMS["map-installed"]
    assert (spec.name, spec.type, spec.required) == ("appids", "string", False)
