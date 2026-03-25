"""Safety conftest: prevent tests from touching real Steam/config files.

Redirects all filesystem paths used by the steam_backlog_enforcer package
to temporary directories.  This stops tests from accidentally:
  - Deleting real game files via uninstall_other_games / uninstall_game
  - Overwriting ~/.config/steam_backlog_enforcer/state.json (losing the
    user's current assignment)
  - Reading real appmanifest files from ~/.local/share/Steam/steamapps
  - Modifying /etc/hosts via the store blocker
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

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
