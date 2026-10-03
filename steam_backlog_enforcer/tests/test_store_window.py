"""Tests for the timed store window (``unblock [minutes]`` + daemon tick)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _store_window
from steam_backlog_enforcer._store_window import (
    MAX_WINDOW_MINUTES,
    open_store_window,
    store_window_tick,
)
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._store_window"


@pytest.fixture(autouse=True)
def _fresh_reblock_memory() -> Iterator[None]:
    """Each test starts with a daemon that has re-blocked for nothing yet."""
    with patch.object(_store_window, "_reblocked_for", set()):
        yield


def _state_ending_in(delta: timedelta) -> State:
    return State(store_unblocked_until=(datetime.now(UTC) + delta).isoformat())


class TestOpenStoreWindow:
    @pytest.mark.parametrize("minutes", [0, MAX_WINDOW_MINUTES + 1])
    def test_rejects_out_of_range(self, minutes: int) -> None:
        state = State()
        with (
            patch(f"{PKG}.unblock_store") as mock_unblock,
            pytest.raises(ValueError, match="between 1 and"),
        ):
            open_store_window(state, minutes)
        mock_unblock.assert_not_called()
        assert not state.store_unblocked_until

    def test_saves_deadline_and_unblocks(self) -> None:
        state = State()
        before = datetime.now(UTC)
        with patch(f"{PKG}.unblock_store", return_value=True) as mock_unblock:
            until = open_store_window(state, 10)
        mock_unblock.assert_called_once()
        assert before + timedelta(minutes=10) <= until
        assert until <= datetime.now(UTC) + timedelta(minutes=10)
        assert State.load().store_unblocked_until == until.isoformat()

    def test_failed_unblock_raises(self) -> None:
        with (
            patch(f"{PKG}.unblock_store", return_value=False),
            pytest.raises(RuntimeError, match="could not unblock"),
        ):
            open_store_window(State(), 5)


class TestStoreWindowTick:
    def test_no_window_does_nothing(self) -> None:
        with (
            patch(f"{PKG}.hosts_blocks_store") as mock_check,
            patch(f"{PKG}.block_store") as mock_block,
        ):
            store_window_tick(Config(), State())
        mock_check.assert_not_called()
        mock_block.assert_not_called()

    def test_malformed_deadline_is_ignored(self) -> None:
        with patch(f"{PKG}.block_store") as mock_block:
            store_window_tick(Config(), State(store_unblocked_until="garbage"))
        mock_block.assert_not_called()

    def test_open_window_undoes_a_reblock(self) -> None:
        state = _state_ending_in(timedelta(minutes=5))
        with (
            patch(f"{PKG}.hosts_blocks_store", return_value=True),
            patch(f"{PKG}.unblock_store") as mock_unblock,
        ):
            store_window_tick(Config(), state)
        mock_unblock.assert_called_once()

    def test_open_window_leaves_open_store_alone(self) -> None:
        state = _state_ending_in(timedelta(minutes=5))
        with (
            patch(f"{PKG}.hosts_blocks_store", return_value=False),
            patch(f"{PKG}.unblock_store") as mock_unblock,
        ):
            store_window_tick(Config(), state)
        mock_unblock.assert_not_called()

    def test_expired_window_reblocks_exactly_once(self) -> None:
        state = _state_ending_in(timedelta(seconds=-1))
        with patch(f"{PKG}.block_store") as mock_block:
            store_window_tick(Config(block_store=True), state)
            store_window_tick(Config(block_store=True), state)
        mock_block.assert_called_once()

    def test_expired_window_respects_block_store_off(self) -> None:
        state = _state_ending_in(timedelta(seconds=-1))
        with patch(f"{PKG}.block_store") as mock_block:
            store_window_tick(Config(block_store=False), state)
        mock_block.assert_not_called()
