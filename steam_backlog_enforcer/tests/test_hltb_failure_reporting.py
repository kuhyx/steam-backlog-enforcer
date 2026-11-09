"""Detail-page failures are counted; ``stats`` prints the tally and fails loud."""

from __future__ import annotations

import asyncio
from typing import Self
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from steam_backlog_enforcer import _stats
from steam_backlog_enforcer._hltb_comp_extract import _fetch_detail_one
from steam_backlog_enforcer._hltb_failures import (
    failure_summary_lines,
    record_failure,
    record_fatal,
    record_success,
    reset_failures,
)


@pytest.fixture(autouse=True)
def _fresh_tally() -> None:
    reset_failures()


class _Page:
    """Fake detail-page response."""

    def __init__(self, status: int) -> None:
        """Store the status."""
        self.status = status

    async def __aenter__(self) -> Self:
        """Enter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit."""

    async def text(self) -> str:
        """Empty page."""
        return ""


def _detail(outcome: object) -> None:
    session = MagicMock()
    if isinstance(outcome, BaseException):
        session.get.side_effect = outcome
    else:
        session.get.return_value = outcome
    asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 77))


@pytest.mark.parametrize(
    ("outcome", "label"),
    [
        (_Page(429), "detail HTTP 429"),
        (_Page(500), "detail HTTP 500"),
        (TimeoutError(), "detail timeouts"),
        (aiohttp.ClientConnectionError(), "detail connection errors"),
    ],
)
def test_detail_failure_is_counted(outcome: object, label: str) -> None:
    """A failed detail fetch shows up in the summary line."""
    _detail(outcome)
    assert f"{label} x1" in failure_summary_lines()[0]


def test_missing_detail_page_is_not_a_failure() -> None:
    """A 404 is HLTB's real answer, not a failed lookup."""
    _detail(_Page(404))
    assert failure_summary_lines() == []


def _stats_with(effect: object) -> None:
    with patch.object(_stats, "_print_stats", side_effect=effect):
        _stats.cmd_stats(MagicMock(), MagicMock())


def test_stats_ends_with_failure_line_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Old data survived: report the failures, exit 0."""
    _stats_with(lambda *_a: record_failure("HTTP 429"))
    out = capsys.readouterr().out.rstrip().splitlines()
    assert out[-1] == (
        "HLTB: 1 lookups failed (HTTP 429 x1), cache kept for those games"
    )


def test_stats_exits_nonzero_when_a_batch_refreshed_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A total failure (auth init or every lookup) is a non-zero exit."""
    msg = "HLTB: rate-limited, nothing refreshed (auth init: HTTP 429)"
    with pytest.raises(SystemExit) as exc:
        _stats_with(lambda *_a: record_fatal(msg))
    assert exc.value.code == 1
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == msg


def test_stats_resets_the_tally_first(capsys: pytest.CaptureFixture[str]) -> None:
    """Failures from an earlier command in the same process are not re-reported."""
    record_fatal("stale")
    _stats_with(None)
    assert "stale" not in capsys.readouterr().out


def test_stats_exits_zero_when_another_lookup_succeeded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One refreshed game anywhere in the command means old data survived: exit 0."""
    msg = "HLTB: all 3 lookups failed, nothing refreshed"

    def one_success_then_a_fatal_batch(*_a: object) -> None:
        record_success()
        record_fatal(msg)

    _stats_with(one_success_then_a_fatal_batch)
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == msg


def test_repeated_fatal_lines_print_once() -> None:
    """Four batches failing auth the same way give one line, not four."""
    for _ in range(4):
        record_fatal("HLTB: rate-limited, nothing refreshed (auth init: timeout)")
    assert failure_summary_lines() == [
        "HLTB: rate-limited, nothing refreshed (auth init: timeout)"
    ]
