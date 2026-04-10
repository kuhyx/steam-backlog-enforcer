"""Safety conftest: prevent tests from touching real Steam/config files.

Redirects all filesystem paths used by the steam_backlog_enforcer package
to temporary directories.  This stops tests from accidentally:
  - Deleting real game files via uninstall_other_games / uninstall_game
  - Overwriting ~/.config/steam_backlog_enforcer/state.json (losing the
    user's current assignment)
  - Reading real appmanifest files from ~/.local/share/Steam/steamapps
  - Modifying /etc/hosts via the store blocker
  - Corrupting the HLTB cache on disk
  - Launching real Steam or calling real subprocess commands
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_filesystem(tmp_path: Path) -> Iterator[None]:
    """Redirect all real filesystem paths to a temporary directory.

    Individual tests that also patch these paths will simply override
    this fixture's patches for the duration of their own ``with`` block.
    """
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    fake_steamapps = tmp_path / "steamapps"
    fake_steamapps.mkdir()
    fake_hosts = tmp_path / "hosts"

    with (
        # Config / state / snapshot paths (used by State.save, Config.save, etc.)
        patch(
            "python_pkg.steam_backlog_enforcer.config.CONFIG_DIR",
            fake_config,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.config.CONFIG_FILE",
            fake_config / "config.json",
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.config.STATE_FILE",
            fake_config / "state.json",
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.config.SNAPSHOT_FILE",
            fake_config / "snapshot.json",
        ),
        # Steam game manifests / install dirs
        patch(
            "python_pkg.steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
            fake_steamapps,
        ),
        # HLTB cache file (computed at import time from CONFIG_DIR, so
        # patching CONFIG_DIR alone does not redirect it)
        patch(
            "python_pkg.steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE",
            fake_config / "hltb_cache.json",
        ),
        # /etc/hosts (store blocker)
        patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_FILE",
            fake_hosts,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.config.HOSTS_FILE",
            fake_hosts,
        ),
    ):
        yield


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
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.run",
            noop_run,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.game_install.subprocess.Popen",
            noop_popen,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.enforcer.subprocess.run",
            noop_run,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            noop_run,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.library_hider.subprocess.run",
            noop_run,
        ),
        patch(
            "python_pkg.steam_backlog_enforcer.library_hider.subprocess.Popen",
            noop_popen,
        ),
    ):
        yield
