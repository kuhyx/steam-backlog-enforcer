"""Closing and reopening the Steam client.

Steam is only ever asked to leave politely. A hung client is a reason to stop
and say so, never to escalate to a signal: SIGKILL mid-write is how a manifest
ends up truncated.
"""

from __future__ import annotations

import logging

import pytest

from steam_installer import recognize, steamctl

LOGGER = logging.getLogger("test-steamctl")


def test_stop_is_a_no_op_when_steam_is_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop is a no op when steam is not running."""
    monkeypatch.setattr(recognize, "steam_client_pids", list)
    called = []
    monkeypatch.setattr(steamctl.subprocess, "run", lambda *a, **k: called.append(a))

    assert steamctl.stop(LOGGER) is False
    assert called == []


def test_stop_asks_steam_to_shut_down_and_waits_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop asks steam to shut down and waits for it."""
    pids = iter([[42], [42], [], []])
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: next(pids))
    seen = {}
    monkeypatch.setattr(
        steamctl.subprocess, "run", lambda cmd, **k: seen.setdefault("cmd", cmd)
    )

    assert steamctl.stop(LOGGER, sleep=lambda _: None) is True
    assert seen["cmd"] == [steamctl.STEAM, "-shutdown"]


def test_stop_gives_up_rather_than_killing_a_client_that_will_not_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop gives up rather than killing a client that will not exit."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [42])
    monkeypatch.setattr(steamctl.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(steamctl.SteamStillRunningError, match="42"):
        steamctl.stop(LOGGER, timeout=1.0, sleep=lambda _: None)


def test_start_launches_steam_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start launches steam detached."""
    seen = {}

    def fake_popen(cmd: list[str], **kwargs: object) -> None:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs

    monkeypatch.setattr(steamctl.subprocess, "Popen", fake_popen)

    steamctl.start(LOGGER)

    assert seen["cmd"] == [steamctl.STEAM]
    assert seen["kwargs"]["start_new_session"] is True
