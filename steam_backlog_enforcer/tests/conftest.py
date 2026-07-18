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
  - Deleting real ~/.steam, ~/.local/share/Steam, etc. via the total-block
    Steam/Proton remnant purge
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
            "steam_backlog_enforcer.config.CONFIG_DIR",
            fake_config,
        ),
        patch(
            "steam_backlog_enforcer.config.CONFIG_FILE",
            fake_config / "config.json",
        ),
        patch(
            "steam_backlog_enforcer.config.STATE_FILE",
            fake_config / "state.json",
        ),
        patch(
            "steam_backlog_enforcer.config.SNAPSHOT_FILE",
            fake_config / "snapshot.json",
        ),
        # Steam game manifests / install dirs. STEAMAPPS_PATH is canonical in
        # _steam_state; game_install imports it, so both bindings need the
        # patch (same gotcha as HOSTS_FILE below).
        patch(
            "steam_backlog_enforcer._steam_state.STEAMAPPS_PATH",
            fake_steamapps,
        ),
        patch(
            "steam_backlog_enforcer.game_install.STEAMAPPS_PATH",
            fake_steamapps,
        ),
        # HLTB cache file (computed at import time from CONFIG_DIR, so
        # patching CONFIG_DIR alone does not redirect it)
        patch(
            "steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE",
            fake_config / "hltb_cache.json",
        ),
        # /etc/hosts (store blocker + total block - each module has its own
        # `from ... import HOSTS_FILE` binding, so each needs its own patch)
        patch(
            "steam_backlog_enforcer.store_blocker.HOSTS_FILE",
            fake_hosts,
        ),
        patch(
            "steam_backlog_enforcer._total_block.HOSTS_FILE",
            fake_hosts,
        ),
        patch(
            "steam_backlog_enforcer.config.HOSTS_FILE",
            fake_hosts,
        ),
        # Total-block lock + IP cache (computed at import time from
        # CONFIG_DIR, so patching CONFIG_DIR alone does not redirect them -
        # same gotcha as HLTB_CACHE_FILE above. A real total-block lock may
        # be active on the host machine; tests must never touch it.)
        patch(
            "steam_backlog_enforcer._total_block.TOTAL_BLOCK_LOCK_FILE",
            fake_config / "total_block_lock.json",
        ),
        patch(
            "steam_backlog_enforcer._total_block._IPTABLES_IP_CACHE_FILE",
            fake_config / "total_block_ip_cache.json",
        ),
        patch(
            "steam_backlog_enforcer._total_block._STEAM_PURGE_LOG_FILE",
            fake_config / "total_block_purge_log.json",
        ),
        # Steam/Proton remnant paths (real ~/.steam, ~/.local/share/Steam,
        # etc. - _remove_steam_remnants() deletes these, so tests must never
        # see the real ones)
        patch(
            "steam_backlog_enforcer._total_block._STEAM_REMNANT_PATHS",
            (
                tmp_path / "fake_home" / ".steam",
                tmp_path / "fake_home" / "steam",
                tmp_path / "fake_home" / ".local" / "share" / "Steam",
                tmp_path / "fake_home" / ".steampath",
                tmp_path / "fake_home" / ".steampid",
                tmp_path / "fake_home" / ".config" / "steamtinkerlaunch",
                tmp_path / "fake_home" / ".config" / "CSDSteamBuild",
            ),
        ),
        # Whitelist exception files (_whitelist module-level constants)
        patch(
            "steam_backlog_enforcer._whitelist.APPROVED_EXCEPTIONS_FILE",
            fake_config / "approved_exceptions.json",
        ),
        patch(
            "steam_backlog_enforcer._whitelist.EXCEPTION_AUDIT_LOG",
            fake_config / "exception_audit.log",
        ),
        # _enforce_loop imports CONFIG_FILE directly; patch the local binding so
        # lock_enforcement_files() uses the tmp path instead of the real one.
        patch(
            "steam_backlog_enforcer._enforce_loop.CONFIG_FILE",
            fake_config / "config.json",
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
            "steam_backlog_enforcer.library_hider.subprocess.run",
            noop_run,
        ),
        patch(
            "steam_backlog_enforcer.library_hider.subprocess.Popen",
            noop_popen,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_real_sleep() -> Iterator[None]:
    """No-op every ``time.sleep`` used by the package.

    Several modules call ``time.sleep`` for Steam-launch / install-retry /
    rate-limit pacing.  Individual tests that need to observe sleep
    behaviour can override these patches inside their own ``with`` block.
    """
    noop = MagicMock()
    with (
        patch("steam_backlog_enforcer.game_install.time.sleep", noop),
        patch("steam_backlog_enforcer.library_hider.time.sleep", noop),
        patch("steam_backlog_enforcer.steam_api.time.sleep", noop),
        patch("steam_backlog_enforcer._enforce_loop.time.sleep", noop),
    ):
        yield
