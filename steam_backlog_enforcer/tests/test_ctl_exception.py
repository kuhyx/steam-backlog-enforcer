"""The ``add_exception`` control-socket op.

The web server cannot replace the ``chattr +i`` exceptions file, so the root
daemon writes it. The daemon re-checks the phrase, the reason, the locks and
duplicates itself: a client talking straight to the socket skips nothing.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_ops
from steam_backlog_enforcer import _whitelist_locking as wl
from steam_backlog_enforcer._ctl_protocol import (
    INVALID_PARAMS,
    LOCKED,
    OP_FAILED,
    WRONG_PHRASE,
    CtlError,
)
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx
from steam_backlog_enforcer.tests._main_helpers import VALID_REASON

MOD = "steam_backlog_enforcer._ctl_exception"
APP = 588730
PHRASE = "request exception for Majotori"


def _call(**args: object) -> dict[str, object]:
    full: dict[str, object] = {"app_id": APP, "reason": VALID_REASON, "phrase": PHRASE}
    full.update(args)
    with patch(f"{MOD}.snapshot_game_name", return_value="Majotori"):
        return _ctl_ops.OPS["add_exception"](make_ctx(), full)


def _error(**args: object) -> CtlError:
    with pytest.raises(CtlError) as err:
        _call(**args)
    return err.value


def _approved_ids() -> list[int]:
    if not wl.APPROVED_EXCEPTIONS_FILE.exists():
        return []
    entries = json.loads(wl.APPROVED_EXCEPTIONS_FILE.read_text(encoding="utf-8"))
    return [int(e["app_id"]) for e in entries]


def test_op_is_allowlisted() -> None:
    """The op is in the socket's allowlist."""
    assert "add_exception" in _ctl_ops.OPS


def test_adds_the_exception() -> None:
    """Right phrase and reason: the entry is written and reported."""
    data = _call()
    assert data["app_id"] == APP
    assert "Exception approved for AppID 588730" in str(data["message"])
    assert _approved_ids() == [APP]


def test_wrong_phrase_writes_nothing() -> None:
    """A wrong phrase is refused before the file is touched."""
    assert _error(phrase="wrong").code == WRONG_PHRASE
    assert _approved_ids() == []


def test_phrase_names_app_id_without_snapshot_name() -> None:
    """With no snapshot name the phrase uses AppID=<id>, as the CLI does."""
    args = {
        "app_id": APP,
        "reason": VALID_REASON,
        "phrase": f"request exception for AppID={APP}",
    }
    with patch(f"{MOD}.snapshot_game_name", return_value=None):
        _ctl_ops.OPS["add_exception"](make_ctx(), args)
    assert _approved_ids() == [APP]


def test_short_reason_is_invalid_params() -> None:
    """The reason rule holds at the socket, not only in the CLI."""
    err = _error(reason="too short")
    assert err.code == INVALID_PARAMS
    assert _approved_ids() == []


@pytest.mark.parametrize(
    "args",
    [{"app_id": "x"}, {"app_id": True}, {"app_id": 0}, {"reason": 5}, {"reason": ""}],
)
def test_bad_args_are_invalid_params(args: dict[str, object]) -> None:
    """Non-integer ids, bools and non-text reasons are refused."""
    assert _error(**args).code == INVALID_PARAMS


def test_duplicate_is_invalid_params() -> None:
    """An id already approved is refused by the daemon."""
    _call()
    err = _error()
    assert err.code == INVALID_PARAMS
    assert "already in the approved exceptions list" in err.message
    assert _approved_ids() == [APP]


def test_lock_refuses() -> None:
    """A lock the CLI honours is honoured here too."""
    with patch(f"{MOD}.check_locks", side_effect=CtlError(LOCKED, "locked")):
        assert _error().code == LOCKED
    assert _approved_ids() == []


def test_write_failure_is_op_failed() -> None:
    """A file the daemon cannot write fails the op with the reason."""
    with patch(f"{MOD}.add_pending_exception", side_effect=OSError("read-only fs")):
        err = _error()
    assert err.code == OP_FAILED
    assert "read-only fs" in err.message


def test_relock_failure_keeps_entry_and_fails_loudly() -> None:
    """Saved but not locked again: entry and audit line stay, the op fails."""
    with patch.object(wl, "_relock", return_value=False):
        err = _error()
    assert err.code == OP_FAILED
    assert err.message == "exception saved but file not locked"
    assert _approved_ids() == [APP]
    assert f"APPROVED | app_id={APP}" in wl.EXCEPTION_AUDIT_LOG.read_text(
        encoding="utf-8"
    )
