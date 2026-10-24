"""The LeetCode gaming hour needs the day paid in full (earned_time 0.18.0).

kuhy, 2026-10-24: Saturday cost 5 credits, one problem was solved, and the
+1 h gaming paid anyway. Only the signed ``leetcode`` charge that covers the
day earns while the gate is on; on a day the gate stands down (free, or sick
without ``leetcode``) one solve earns. This daemon runs as root without the
free-day and sick-day pools, so it asks leetcode-guard's endpoint for the
live ``gate_off`` fact -- and an unreachable endpoint means "on" (no hour).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _leetcode_bonus, _leetcode_ledger
from steam_backlog_enforcer._leetcode_bonus import leetcode_solved_today, reset_cache
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._leetcode_bonus"
_API = "steam_backlog_enforcer._status_api"
_URL = "http://127.0.0.1:8771/api/status"


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    reset_cache()
    yield
    reset_cache()


def _serve(block: dict[str, bool]) -> object:
    """Patch the endpoint to answer ``block`` (checked) with a 200."""
    payload = json.dumps({"leetcode": {"checked": True, **block}}).encode()
    conn = patch(f"{_API}.http.client.HTTPConnection")
    mock = conn.start()
    resp = mock.return_value.getresponse.return_value
    resp.status = 200
    resp.read.return_value = payload
    return conn


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        # One solve of five, gate on: no hour -- the 2026-10-24 bug.
        ({"solved_today": True, "settled_by_credit": False, "gate_off": False}, False),
        ({"solved_today": True, "settled_by_credit": False}, False),
        ({"solved_today": True, "settled_by_credit": True, "gate_off": False}, True),
        # A stood-down day has no price: one solve earns, no solve does not.
        ({"solved_today": True, "settled_by_credit": False, "gate_off": True}, True),
        ({"solved_today": False, "settled_by_credit": False, "gate_off": True}, False),
    ],
)
def test_the_fallback_pays_only_a_paid_day(
    block: dict[str, bool], *, expected: bool
) -> None:
    conn = _serve(block)
    try:
        assert _leetcode_bonus._fetch_leetcode_today(_URL) is expected
    finally:
        conn.stop()


@pytest.mark.parametrize("off", [True, False])
def test_gate_off_is_read_from_the_endpoint(*, off: bool) -> None:
    conn = _serve({"solved_today": False, "gate_off": off})
    try:
        assert _leetcode_bonus.gate_off_now(_URL) is off
    finally:
        conn.stop()


def test_an_unreachable_endpoint_means_the_gate_is_on() -> None:
    with patch(f"{_PKG}.get_status", side_effect=OSError("refused")):
        assert _leetcode_bonus.gate_off_now(_URL) is False


def test_an_old_endpoint_without_the_field_means_on() -> None:
    conn = _serve({"solved_today": True})
    try:
        assert _leetcode_bonus.gate_off_now(_URL) is False
    finally:
        conn.stop()


def test_the_ledger_read_is_told_the_live_answer() -> None:
    with (
        patch(f"{_PKG}.gate_off_now", return_value=True),
        patch(f"{_PKG}.read_ledger_solved_today", return_value=True) as read,
    ):
        assert leetcode_solved_today(Config()) is True
    assert read.call_args.kwargs["gate_off"] is True


def test_the_ledger_reader_passes_it_on(tmp_path: Path) -> None:
    with patch.object(
        _leetcode_ledger.earned_time, "done_today", return_value=True
    ) as done:
        _leetcode_ledger.read_ledger_solved_today(tmp_path / "l.json", gate_off=True)
    assert done.call_args.kwargs["gate_off"] is True
