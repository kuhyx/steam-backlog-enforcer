"""Shared builders and runner for the ``_fetch_leisure_times`` tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from steam_backlog_enforcer._hltb_detail import _fetch_leisure_times
from steam_backlog_enforcer._hltb_types import HLTBResult

if TYPE_CHECKING:
    from steam_backlog_enforcer._hltb_types import ProgressCb, _HLTBExtras


def tf2_result(hltb_game_id: int = 12345) -> HLTBResult:
    """Return the TF2 search hit (50 h estimate) the leisure tests refine."""
    return HLTBResult(
        app_id=440,
        game_name="TF2",
        completionist_hours=50.0,
        similarity=1.0,
        hltb_game_id=hltb_game_id,
    )


def helltaker_result() -> HLTBResult:
    """Return the Helltaker search hit whose DLC the leisure tests add up."""
    return HLTBResult(
        app_id=1289310,
        game_name="Helltaker",
        completionist_hours=1.0,
        similarity=1.0,
        hltb_game_id=78118,
    )


def run_leisure(
    results: list[HLTBResult],
    detail: object = None,
    *,
    details: list[object] | None = None,
    progress_cb: ProgressCb | None = None,
    extras: _HLTBExtras | None = None,
) -> dict[int, float]:
    """Run ``_fetch_leisure_times`` with each detail page answering ``detail``.

    ``details`` instead answers successive detail fetches in order. Returns
    the hours cache the run filled.
    """
    cache: dict[int, float] = {}
    # A side_effect list, when given, wins over return_value.
    with patch(
        "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
        new_callable=AsyncMock,
        return_value=detail,
        side_effect=details,
    ):
        asyncio.run(
            _fetch_leisure_times(results, cache, {}, progress_cb, extras=extras)
        )
    return cache
