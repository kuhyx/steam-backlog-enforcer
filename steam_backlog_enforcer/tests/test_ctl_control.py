"""Tests for ``_ctl_control``: the enforce loop's handle on the socket.

``os.geteuid``, the desktop-user lookup and the server are mocked; no socket
is ever bound and no tick is actually billed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_control
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx


class TestDaemonControl:
    """The handle the loop holds."""

    def test_properties(self) -> None:
        ctx = make_ctx()
        control = _ctl_control.DaemonControl(ctx, None)
        assert control.tick_lock is ctx.tick_lock
        assert control.restart_requested is False
        ctx.restart_event.set()
        assert control.restart_requested is True

    def test_flush_without_request_does_nothing(self) -> None:
        control = _ctl_control.DaemonControl(make_ctx(), None)
        with patch.object(_ctl_control, "playtime_tick") as tick:
            assert (
                control.flush_for_restart(
                    Config(), MagicMock(), interval=3.0, demo=False
                )
                is False
            )
        tick.assert_not_called()

    def test_flush_bills_marks_and_exits(self) -> None:
        ctx = make_ctx()
        ctx.restart_event.set()
        control = _ctl_control.DaemonControl(ctx, None)
        config, session = Config(), MagicMock()
        with (
            patch.object(_ctl_control, "playtime_tick") as tick,
            patch.object(_ctl_control, "record_exit") as record,
        ):
            assert control.flush_for_restart(config, session, interval=3.0, demo=False)
        tick.assert_called_once_with(config, interval=3.0, session=session, demo=False)
        record.assert_called_once()

    def test_close_stops_server(self) -> None:
        server = MagicMock()
        _ctl_control.DaemonControl(make_ctx(), server).close()
        server.stop.assert_called_once()

    def test_close_inert(self) -> None:
        _ctl_control.DaemonControl(make_ctx(), None).close()


class TestIsSupervised:
    """systemd sets INVOCATION_ID for its services."""

    def test_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INVOCATION_ID", "abc")
        assert _ctl_control._is_supervised() is True

    def test_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        assert _ctl_control._is_supervised() is False


class TestStartControl:
    """Only the real root daemon serves."""

    def test_demo_is_inert(self) -> None:
        with patch.object(_ctl_control, "CtlServer") as server:
            control = _ctl_control.start_control(Config(), demo=True)
        server.assert_not_called()
        assert control._server is None

    def test_non_root_is_inert(self) -> None:
        with (
            patch.object(_ctl_control.os, "geteuid", return_value=1000),
            patch.object(_ctl_control, "CtlServer") as server,
        ):
            control = _ctl_control.start_control(Config(), demo=False)
        server.assert_not_called()
        assert control._server is None

    @pytest.mark.parametrize("user", [None, "ghost"])
    def test_unknown_desktop_user_fails_closed(self, user: str | None) -> None:
        with (
            patch.object(_ctl_control.os, "geteuid", return_value=0),
            patch.object(_ctl_control, "resolve_desktop_user", return_value=user),
            patch.object(_ctl_control.pwd, "getpwnam", side_effect=KeyError(user)),
            patch.object(_ctl_control, "CtlServer") as server,
        ):
            control = _ctl_control.start_control(Config(), demo=False)
        server.assert_not_called()
        assert control._server is None

    def test_root_desktop_user_fails_closed(self) -> None:
        entry = MagicMock(pw_uid=0, pw_gid=0)
        with (
            patch.object(_ctl_control.os, "geteuid", return_value=0),
            patch.object(_ctl_control, "resolve_desktop_user", return_value="root"),
            patch.object(_ctl_control.pwd, "getpwnam", return_value=entry),
            patch.object(_ctl_control, "CtlServer") as server,
        ):
            control = _ctl_control.start_control(Config(), demo=False)
        server.assert_not_called()
        assert control._server is None

    @pytest.mark.parametrize("started", [True, False], ids=["bound", "bind_failed"])
    def test_serves_for_desktop_user(self, *, started: bool) -> None:
        entry = MagicMock(pw_uid=1000, pw_gid=1001)
        with (
            patch.object(_ctl_control.os, "geteuid", return_value=0),
            patch.object(_ctl_control, "resolve_desktop_user", return_value="kuhy"),
            patch.object(_ctl_control.pwd, "getpwnam", return_value=entry),
            patch.object(_ctl_control, "CtlServer") as server_cls,
        ):
            server_cls.return_value.start.return_value = started
            control = _ctl_control.start_control(Config(), demo=False)
        assert server_cls.call_args.kwargs == {
            "desktop_uid": 1000,
            "desktop_gid": 1001,
        }
        assert (control._server is not None) is started
