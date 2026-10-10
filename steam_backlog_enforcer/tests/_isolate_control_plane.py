"""Autouse isolation of the control plane and the HLTB endpoint memo.

Redirects the web cover-art caches, the daemon control socket, restart
markers, backups and web job store (all under ``/var/lib``, ``/run`` or the
real ``~/.local/state``) into ``tmp_path``, and forgets the remembered HLTB
search URL around every test.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixtures by name, which is what registers them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._hltb_search_api import forget_hltb_search_url

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_control_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Redirect the daemon control socket, restart state, backups and job dirs.

    Without it a test that reaches the restart-exit marker or a job store
    touches ``/var/lib/steam-backlog-enforcer`` or the real
    ``~/.local/state`` (and the web token lives under ``XDG_RUNTIME_DIR``).
    Default arguments bound at import (``path=SOCKET_PATH``) cannot be
    redirected here: tests pass an explicit path for those.
    """
    state = tmp_path / "ctl_state"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg_runtime"))
    with (
        patch("steam_backlog_enforcer._ctl_gap.RESTART_EXIT_FILE", state / "exit.json"),
        patch(
            "steam_backlog_enforcer._ctl_restart.RESTART_STATE_FILE",
            state / "restart.json",
        ),
        patch("steam_backlog_enforcer._ctl_protocol.SOCKET_PATH", state / "ctl.sock"),
        patch("steam_backlog_enforcer._ctl_client.SOCKET_PATH", state / "ctl.sock"),
        patch("steam_backlog_enforcer._ctl_server.SOCKET_PATH", state / "ctl.sock"),
        patch("steam_backlog_enforcer._backups.BACKUPS_DIR", tmp_path / "backups"),
        patch("steam_backlog_enforcer.jobs._store.JOBS_DIR", tmp_path / "jobs"),
    ):
        yield


@pytest.fixture(autouse=True)
def _isolate_cover_art(tmp_path: Path) -> Iterator[None]:
    """Cover art: Steam's librarycache is read, the art cache is written."""
    with (
        patch(
            "steam_backlog_enforcer._web_art.LIBRARYCACHE",
            tmp_path / "fake_home" / "librarycache",
        ),
        patch("steam_backlog_enforcer._web_art.ART_CACHE_DIR", tmp_path / "art"),
    ):
        yield


@pytest.fixture(autouse=True)
def _forget_hltb_search_url() -> Iterator[None]:
    """Start every test without a remembered HLTB search endpoint.

    ``_get_hltb_search_url`` memoises a discovered URL for half an hour; a
    value left behind by one test would hide the discovery path in the next.
    """
    forget_hltb_search_url()
    yield
    forget_hltb_search_url()


@pytest.fixture(autouse=True)
def _forget_hltb_search_url() -> Iterator[None]:
    """Start every test without a remembered HLTB search endpoint.

    ``_get_hltb_search_url`` memoises a discovered URL for half an hour; a
    value left behind by one test would hide the discovery path in the next.
    """
    forget_hltb_search_url()
    yield
    forget_hltb_search_url()
