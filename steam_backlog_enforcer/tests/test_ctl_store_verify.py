"""Control-socket side of the store checks: failed unblocks and re-block reports."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_ops
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer._store_verify import (
    Check,
    StoreCheckReport,
    StoreVerifyError,
)
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx

if TYPE_CHECKING:
    from collections.abc import Iterator

_PHRASE = "unblock the store for 5 minutes"


@pytest.fixture(autouse=True)
def hand_back() -> Iterator[MagicMock]:
    """Never chown the real state file."""
    with patch.object(_ctl_ops, "_hand_back_state_file") as fake:
        yield fake


def test_failed_check_is_op_failed_with_report() -> None:
    """A failed check is op_failed, naming the check and carrying the report."""
    report = StoreCheckReport("unblock", "t", [Check("https", ok=False, detail="x")])
    with (
        patch.object(_ctl_ops, "check_locks"),
        patch.object(
            _ctl_ops, "open_store_window", side_effect=StoreVerifyError(report)
        ),
        pytest.raises(CtlError) as caught,
    ):
        _ctl_ops.op_store_unblock(make_ctx(), {"minutes": 5, "phrase": _PHRASE})
    assert caught.value.code == "op_failed"
    assert caught.value.message == "Store unblock failed: https"
    assert caught.value.data["report"] == report.to_wire()


def test_store_reports_hands_back_queued_reports() -> None:
    """store_reports returns what the window queued, then nothing."""
    queued = [{"title": "Store re-block verification failed: dns"}]
    with patch.object(_ctl_ops, "take_store_reports", return_value=queued):
        assert _ctl_ops.op_store_reports(make_ctx(), {}) == {"reports": queued}
