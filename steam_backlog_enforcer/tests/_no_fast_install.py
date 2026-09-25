"""Autouse guard that keeps tests away from steam-game-installer and /proc.

Split out of ``conftest.py`` to keep it inside the 250-line cap; ``conftest``
imports the fixture by name, which is what registers it.

The real installer shuts the user's Steam down, so no test may find it: the
installer path is pointed at a file that does not exist. The "is an installer
running" scan reads the real /proc, so it answers False unless a test says
otherwise - and it is imported by name into several modules, so every binding
is patched. Tests that exercise the real scan import the function directly,
which captures it before this fixture runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _fast_install

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_RUNNING_BINDINGS = (
    "steam_backlog_enforcer._steam_restart_guard.fast_install_running",
    "steam_backlog_enforcer.game_install.fast_install_running",
    "steam_backlog_enforcer._steam_client.fast_install_running",
    "steam_backlog_enforcer._steam_launch.fast_install_running",
)


@pytest.fixture(autouse=True)
def _no_fast_install(tmp_path: Path) -> Iterator[None]:
    """Hide the real installer, fake the /proc scan, reset run bookkeeping."""
    fake_steamapps = tmp_path / "steamapps"
    fake_steamapps.mkdir(exist_ok=True)
    _fast_install._RUNS.clear()
    _fast_install._FAILED.clear()
    patches = [patch(name, return_value=False) for name in _RUNNING_BINDINGS]
    patches += [
        # Absolute, so `home / _INSTALLER` resolves here and never under ~.
        patch.object(_fast_install, "_INSTALLER", tmp_path / "no-installer" / "run.sh"),
        patch.object(_fast_install, "STEAMAPPS_PATH", fake_steamapps),
    ]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()
        _fast_install._RUNS.clear()
        _fast_install._FAILED.clear()
