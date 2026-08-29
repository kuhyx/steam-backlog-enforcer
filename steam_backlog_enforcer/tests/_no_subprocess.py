"""Autouse guard that stops tests shelling out to real commands.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _block_real_subprocesses() -> Iterator[None]:
    """Block subprocess calls that could launch real Steam or modify system.

    Individual tests that need to test subprocess behaviour should
    patch the specific module's ``subprocess.run`` / ``subprocess.Popen``
    themselves — their local patch will override this one.
    """
    noop_run = MagicMock(return_value=MagicMock(returncode=1))
    noop_popen = MagicMock()

    with (
        patch(
            "steam_backlog_enforcer.game_install.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer.game_install.subprocess.Popen",
            noop_popen,
        ),
        patch(
            "steam_backlog_enforcer.enforcer.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer._total_block.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer._pacman.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer._total_block_hosts.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer._total_block_iptables.subprocess.run",
            noop_run,
        ),
        # library_hider no longer spawns: its launch/process code lives in
        # _steam_launch / _steam_process, and _steam_client starts the client.
        # Every module that can spawn must be patched here, or a test could
        # fire a real `sudo -u kuhy steam`.
        patch(
            "steam_backlog_enforcer._steam_launch.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer._steam_launch.subprocess.Popen",
            noop_popen,
        ),
        patch(
            "steam_backlog_enforcer._steam_process.subprocess.Popen",
            noop_popen,
        ),
        patch(
            "steam_backlog_enforcer._steam_client.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer._steam_client.subprocess.Popen",
            noop_popen,
        ),
        # The single most important patch in this file. _playtime_block._run
        # executes `mount --bind` against paths that, unpatched, are the real
        # /usr/bin/steam. A test that reached the real subprocess would mask
        # the user's actual Steam install with a refusal stub.
        patch(
            "steam_backlog_enforcer._playtime_run.subprocess.run",
            noop_run,
        ),
        # A real `npm run build` here would rewrite web/dist/index.html, which
        # then perturbs frontend_is_stale() for every later test in the run.
        patch(
            "steam_backlog_enforcer._web_build.subprocess.run",
            noop_run,
        ),
    ):
        yield
