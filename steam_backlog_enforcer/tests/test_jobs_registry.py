"""Tests for ``jobs._registry``: which command runs as which job handler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._prompter import PromptAbortedError
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.jobs import _registry
from steam_backlog_enforcer.jobs._errors import PrivilegedViaDaemonError
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS

_PROGRESS = MagicMock()
_PROMPTER = MagicMock()
_PREFIX = "steam_backlog_enforcer.jobs._registry."


def test_every_flagged_command_has_a_handler() -> None:
    """The two tables describe the same commands."""
    assert set(_registry.HANDLERS) == set(JOB_FLAGS)


class TestAssignment:
    """The data every backlog job returns."""

    def test_no_game_assigned(self) -> None:
        """An empty name reads as ``None``."""
        data = _registry._assignment(State())
        assert data == {"current_app_id": None, "current_game_name": None}

    def test_game_assigned(self) -> None:
        """The assigned game is reported."""
        state = State(current_app_id=620, current_game_name="Portal 2")
        assert _registry._assignment(state)["current_game_name"] == "Portal 2"


class TestCliWrappers:
    """``(config, state)`` and ``(config, state, args)`` commands."""

    def test_cli_runs_command_and_reports_assignment(self) -> None:
        """The command gets the loaded config and state."""
        command = MagicMock()
        handler = _registry._cli(command)
        data = handler({}, _PROGRESS, _PROMPTER)
        config, state = command.call_args.args
        assert isinstance(state, State)
        assert config is not None
        assert data == {
            "current_app_id": state.current_app_id,
            "current_game_name": None,
        }

    def test_with_args_passes_the_param_as_argv(self) -> None:
        """One stringified positional arg."""
        command = MagicMock()
        handler = _registry._with_args(command, "app_id")
        handler({"app_id": 620}, _PROGRESS, _PROMPTER)
        assert command.call_args.args[2] == ["620"]


class TestAddException:
    """``add-exception <app_id> --reason <reason>``."""

    def test_builds_the_cli_argv(self) -> None:
        """Params become the argument list the CLI parses."""
        with patch(_PREFIX + "cmd_add_exception") as command:
            data = _registry._add_exception(
                {"app_id": 620, "reason": "one two three four five"},
                _PROGRESS,
                _PROMPTER,
            )
        command.assert_called_once_with(["620", "--reason", "one two three four five"])
        assert data == {"app_id": 620}


class TestEnforceDemo:
    """Only the demo runs as a job."""

    def test_demo_runs_cmd_enforce(self) -> None:
        """The demo gets ``--demo`` and reports the exit code."""
        with patch(_PREFIX + "cmd_enforce", return_value=0) as command:
            data = _registry._enforce_demo({"demo": 1}, _PROGRESS, _PROMPTER)
        assert command.call_args.args[2] == ["--demo"]
        assert data == {"exit_code": 0}

    def test_refused_demo_fails_the_job(self) -> None:
        """A non-zero demo exit is a failed job, never a quiet success."""
        with (
            patch(_PREFIX + "cmd_enforce", return_value=1),
            pytest.raises(SystemExit) as exc,
        ):
            _registry._enforce_demo({"demo": 1}, _PROGRESS, _PROMPTER)
        assert exc.value.code == 1

    def test_real_enforce_goes_to_daemon(self) -> None:
        """Without ``demo`` the job refuses."""
        with pytest.raises(PrivilegedViaDaemonError):
            _registry._enforce_demo({"demo": 0}, _PROGRESS, _PROMPTER)


class TestRestoreBackup:
    """Replacing the state after a typed phrase."""

    def test_declined_phrase_aborts(self) -> None:
        """No phrase, no restore."""
        with (
            patch(_PREFIX + "confirm_phrase", return_value=False),
            patch(_PREFIX + "restore_backup") as restore,
            pytest.raises(PromptAbortedError),
        ):
            _registry._restore_backup({"backup_id": "b1"}, _PROGRESS, _PROMPTER)
        restore.assert_not_called()

    def test_restore_without_previous_state(self) -> None:
        """Nothing was replaced, so no second message."""
        with (
            patch(_PREFIX + "confirm_phrase", return_value=True) as confirm,
            patch(_PREFIX + "restore_backup", return_value=None),
            patch(_PREFIX + "_echo") as echo,
        ):
            data = _registry._restore_backup({"backup_id": "b1"}, _PROGRESS, _PROMPTER)
        assert confirm.call_args.kwargs == {"backup_id": "b1"}
        echo.assert_called_once_with("Restored backup b1.")
        assert data == {"restored": "b1", "previous_backup": None}

    def test_restore_reports_the_saved_previous_state(self) -> None:
        """The replaced state's backup id is announced and returned."""
        with (
            patch(_PREFIX + "confirm_phrase", return_value=True),
            patch(_PREFIX + "restore_backup", return_value=SimpleNamespace(id="b0")),
            patch(_PREFIX + "_echo") as echo,
        ):
            data = _registry._restore_backup({"backup_id": "b1"}, _PROGRESS, _PROMPTER)
        assert echo.call_count == 2
        assert data == {"restored": "b1", "previous_backup": "b0"}


class TestViaDaemon:
    """Privileged commands refuse to run as jobs."""

    @pytest.mark.parametrize("command", ["gaming-reset", "unblock", "buy-dlc"])
    def test_handler_refuses(self, command: str) -> None:
        """The placeholder raises the routing error naming the command."""
        with pytest.raises(PrivilegedViaDaemonError) as info:
            _registry.HANDLERS[command]({}, _PROGRESS, _PROMPTER)
        assert info.value.command == command
