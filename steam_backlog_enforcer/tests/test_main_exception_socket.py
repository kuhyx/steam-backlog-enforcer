"""``add-exception`` as plain kuhy goes through the root daemon.

The exceptions file is ``chattr +i``; only root can replace it. Under sudo the
CLI still writes the file itself; everyone else asks the daemon.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_client
from steam_backlog_enforcer._ctl_protocol import (
    INVALID_PARAMS,
    CtlError,
    DaemonUnreachableError,
)
from steam_backlog_enforcer._whitelist_relock import ExceptionNotLockedError
from steam_backlog_enforcer.main import cmd_add_exception
from steam_backlog_enforcer.tests._main_helpers import VALID_REASON

EXC_PKG = "steam_backlog_enforcer.main.exception"
ARGS = ["440", "--reason", VALID_REASON]
PHRASE = "request exception for AppID=440"


def _run(*, euid: int) -> list[str]:
    """Run the command with the phrase typed; returns what it echoed."""
    with (
        patch(f"{EXC_PKG}.os.geteuid", return_value=euid),
        patch("builtins.input", return_value=PHRASE),
        patch(f"{EXC_PKG}._echo") as echo,
    ):
        cmd_add_exception(ARGS)
    return [str(c.args[0]) if c.args else "" for c in echo.call_args_list]


def test_plain_user_asks_the_daemon() -> None:
    """Non-root sends id, reason and phrase to the socket; no direct write."""
    with (
        patch.object(_ctl_client, "add_exception", return_value="ok msg") as client,
        patch(f"{EXC_PKG}.add_pending_exception") as direct,
    ):
        out = _run(euid=1000)
    client.assert_called_once_with(440, VALID_REASON, PHRASE)
    direct.assert_not_called()
    assert out[-1] == "ok msg"


def test_root_writes_directly() -> None:
    """Under sudo the file is written in-process, as before."""
    with (
        patch.object(_ctl_client, "add_exception") as client,
        patch(f"{EXC_PKG}.add_pending_exception", return_value="direct") as direct,
    ):
        out = _run(euid=0)
    direct.assert_called_once_with(440, VALID_REASON)
    client.assert_not_called()
    assert out[-1] == "direct"


def test_unreachable_message_text(capsys: pytest.CaptureFixture[str]) -> None:
    """The message names /run/steam-backlog-enforcer/ctl.sock and sudo."""
    with (
        patch(f"{EXC_PKG}.os.geteuid", return_value=1000),
        patch("builtins.input", return_value=PHRASE),
        patch.object(
            _ctl_client, "add_exception", side_effect=DaemonUnreachableError("gone")
        ),
        patch(f"{EXC_PKG}._echo", side_effect=print),
        pytest.raises(SystemExit),
    ):
        cmd_add_exception(ARGS)
    out = capsys.readouterr().out
    assert "/run/steam-backlog-enforcer/ctl.sock" in out
    assert "sudo ./run.sh add-exception" in out


def test_daemon_refusal_exits_with_its_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal (duplicate, locked, ...) prints the daemon's text, exit 1."""
    err = CtlError(
        INVALID_PARAMS, "AppID 440 is already in the approved exceptions list."
    )
    with (
        patch(f"{EXC_PKG}.os.geteuid", return_value=1000),
        patch("builtins.input", return_value=PHRASE),
        patch.object(_ctl_client, "add_exception", side_effect=err),
        patch(f"{EXC_PKG}._echo", side_effect=print),
        pytest.raises(SystemExit, match="1"),
    ):
        cmd_add_exception(ARGS)
    assert "already in the approved exceptions list" in capsys.readouterr().out


def test_root_relock_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Under sudo a file left unlocked is an error too, not a success."""
    with (
        patch(f"{EXC_PKG}.os.geteuid", return_value=0),
        patch("builtins.input", return_value=PHRASE),
        patch(
            f"{EXC_PKG}.add_pending_exception",
            side_effect=ExceptionNotLockedError("exception saved but file not locked"),
        ),
        patch(f"{EXC_PKG}._echo", side_effect=print),
        pytest.raises(SystemExit, match="1"),
    ):
        cmd_add_exception(ARGS)
    assert "exception saved but file not locked" in capsys.readouterr().out
