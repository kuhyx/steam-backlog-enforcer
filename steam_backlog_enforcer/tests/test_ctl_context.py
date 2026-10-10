"""Tests for ``_ctl_context``: the tick lock, argument readers and lock gate."""

from __future__ import annotations

from contextlib import AbstractContextManager, ExitStack
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_context
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx


def _code(exc: pytest.ExceptionInfo[CtlError]) -> str:
    return exc.value.code


class TestHoldTick:
    """The lock is held for the body and always released."""

    def test_holds_and_releases(self) -> None:
        ctx = make_ctx()
        with _ctl_context.hold_tick(ctx):
            assert ctx.tick_lock.locked()
        assert not ctx.tick_lock.locked()

    def test_releases_after_error(self) -> None:
        ctx = make_ctx()
        with pytest.raises(RuntimeError), _ctl_context.hold_tick(ctx):
            msg = "boom"
            raise RuntimeError(msg)
        assert not ctx.tick_lock.locked()

    def test_busy_when_loop_keeps_the_lock(self) -> None:
        ctx = make_ctx()
        ctx.tick_lock.acquire()
        with (
            patch.object(_ctl_context, "LOCK_WAIT_SECONDS", 0.01),
            pytest.raises(CtlError) as caught,
            _ctl_context.hold_tick(ctx),
        ):
            pass
        assert _code(caught) == "busy"


class TestRequirePhrase:
    """The typed confirmation phrase."""

    def test_accepts_exact_phrase_with_padding(self) -> None:
        _ctl_context.require_phrase(
            "block-gaming", "  block all gaming for 3 days ", days=3
        )

    def test_non_string(self) -> None:
        with pytest.raises(CtlError) as caught:
            _ctl_context.require_phrase("gaming-unblock", 5)
        assert _code(caught) == "invalid_params"

    def test_wrong_phrase(self) -> None:
        with pytest.raises(CtlError) as caught:
            _ctl_context.require_phrase("gaming-unblock", "nope")
        assert _code(caught) == "wrong_phrase"

    def test_command_without_phrase_is_never_accepted(self) -> None:
        with pytest.raises(CtlError) as caught:
            _ctl_context.require_phrase("status", "")
        assert _code(caught) == "wrong_phrase"


class TestIntArg:
    """Bounded integer arguments."""

    def test_valid(self) -> None:
        assert _ctl_context.int_arg({"n": 5}, "n", 1, 10) == 5

    @pytest.mark.parametrize("value", [True, "5", 5.0, None])
    def test_wrong_type(self, value: object) -> None:
        with pytest.raises(CtlError, match="must be an integer"):
            _ctl_context.int_arg({"n": value}, "n", 1, 10)

    def test_missing(self) -> None:
        with pytest.raises(CtlError, match="must be an integer"):
            _ctl_context.int_arg({}, "n", 1, 10)

    @pytest.mark.parametrize("value", [0, 11])
    def test_out_of_range(self, value: int) -> None:
        with pytest.raises(CtlError, match="between 1 and 10"):
            _ctl_context.int_arg({"n": value}, "n", 1, 10)


class TestStrArg:
    """Non-empty string arguments."""

    def test_valid(self) -> None:
        assert _ctl_context.str_arg({"s": "abc"}, "s") == "abc"

    @pytest.mark.parametrize("value", ["", 5, None])
    def test_invalid(self, value: object) -> None:
        with pytest.raises(CtlError, match="non-empty string"):
            _ctl_context.str_arg({"s": value}, "s")


def _locks(*, block: bool, manual: bool) -> AbstractContextManager[object]:
    """Pin both lock predicates."""
    stack = ExitStack()
    stack.enter_context(
        patch.object(_ctl_context, "is_total_block_active", return_value=block)
    )
    stack.enter_context(
        patch.object(_ctl_context, "is_manual_pick_locked", return_value=manual)
    )
    return stack


class TestCheckLocks:
    """The socket honours the same locks as the CLI."""

    def test_nothing_locked(self) -> None:
        with _locks(block=False, manual=False):
            _ctl_context.check_locks("block-gaming")

    def test_total_block_refuses(self) -> None:
        with _locks(block=True, manual=False), pytest.raises(CtlError) as caught:
            _ctl_context.check_locks("gaming-reset")
        assert _code(caught) == "locked"

    def test_total_block_exempt_command(self) -> None:
        with _locks(block=True, manual=False):
            _ctl_context.check_locks("gaming-unblock")

    def test_manual_pick_lock_refuses(self) -> None:
        with _locks(block=False, manual=True), pytest.raises(CtlError) as caught:
            _ctl_context.check_locks("unblock")
        assert _code(caught) == "locked"

    def test_manual_pick_exempt_command(self) -> None:
        with _locks(block=False, manual=True):
            _ctl_context.check_locks("gaming-reset")
