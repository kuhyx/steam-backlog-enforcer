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

# Imported for its autouse side effect: naming it here registers it.
from steam_backlog_enforcer.tests._isolate_playtime import _isolate_playtime
from steam_backlog_enforcer.tests._no_subprocess import _block_real_subprocesses
from steam_backlog_enforcer.tests._no_workout_http import _no_workout_http

# Re-exported so ruff --fix does not delete the imports above: pytest
# registers autouse fixtures by name, so they look unused to the linter.
__all__ = ["_block_real_subprocesses", "_isolate_playtime", "_no_workout_http"]

from steam_backlog_enforcer.tests._total_block_paths import (
    BLOCK,
    HOSTS,
    IPTABLES,
    PURGE,
    Paths,
    build_paths,
)

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
            "steam_backlog_enforcer._total_block_hosts.HOSTS_FILE",
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
            "steam_backlog_enforcer._total_block_iptables._IPTABLES_IP_CACHE_FILE",
            fake_config / "total_block_ip_cache.json",
        ),
        patch(
            "steam_backlog_enforcer._total_block_purge._STEAM_PURGE_LOG_FILE",
            fake_config / "total_block_purge_log.json",
        ),
        # Steam/Proton remnant paths (real ~/.steam, ~/.local/share/Steam,
        # etc. - _remove_steam_remnants() deletes these, so tests must never
        # see the real ones)
        patch(
            "steam_backlog_enforcer._total_block_purge._STEAM_REMNANT_PATHS",
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
        # Derived from CONFIG_DIR at import time, so it captures the REAL path
        # before this fixture redirects CONFIG_DIR. Without it the suite
        # rewrites the user's owned-games cache.
        patch(
            "steam_backlog_enforcer._owned_apps_cache._OWNED_IDS_CACHE_FILE",
            fake_config / "owned_app_ids_cache.json",
        ),
        # Whitelist exception files (module-level constants; these live in
        # _whitelist_locking, which is where the code that reads them is)
        patch(
            "steam_backlog_enforcer._whitelist_locking.APPROVED_EXCEPTIONS_FILE",
            fake_config / "approved_exceptions.json",
        ),
        patch(
            "steam_backlog_enforcer._whitelist_locking.EXCEPTION_AUDIT_LOG",
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
def _no_real_sleep() -> Iterator[None]:
    """No-op every ``time.sleep`` used by the package.

    Several modules call ``time.sleep`` for Steam-launch / install-retry /
    rate-limit pacing.  Individual tests that need to observe sleep
    behaviour can override these patches inside their own ``with`` block.
    """
    noop = MagicMock()
    with (
        patch("steam_backlog_enforcer._steam_client.time.sleep", noop),
        patch("steam_backlog_enforcer._steam_launch.time.sleep", noop),
        patch("steam_backlog_enforcer._steam_api_client.time.sleep", noop),
        patch("steam_backlog_enforcer._enforce_loop.time.sleep", noop),
    ):
        yield


# ──────────────────────────────────────────────────────────────
# Total-block path redirection
#
# Lives here rather than in a helper module because pytest resolves
# fixtures by name: an imported fixture looks unused to ruff, and this
# repo runs `ruff --fix --unsafe-fixes`, which deletes the import.
# ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def total_block_paths(tmp_path: Path) -> Iterator[Paths]:
    """Redirect every total-block path constant to tmp_path for one test."""
    built = build_paths(tmp_path)
    with (
        patch(f"{BLOCK}.TOTAL_BLOCK_LOCK_FILE", built.lock_file),
        patch(f"{IPTABLES}._IPTABLES_IP_CACHE_FILE", built.ip_cache_file),
        patch(f"{HOSTS}.HOSTS_FILE", built.hosts_file),
        patch(f"{PURGE}._STEAM_PURGE_LOG_FILE", built.purge_log_file),
        patch(f"{PURGE}._STEAM_REMNANT_PATHS", built.remnant_paths),
    ):
        yield built


# ──────────────────────────────────────────────────────────────
# Live process-table isolation
#
# The Steam-restart guard asks whether a game is running by scanning
# /proc for SteamAppId. Unpatched, that reads the *developer's* real
# process table: running the suite while playing a game made three
# restart tests fail on 2026-08-28. Tests that care about the guard
# patch this themselves.
# ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_live_games() -> Iterator[None]:
    """Report no running games unless a test says otherwise."""
    with patch(
        "steam_backlog_enforcer._steam_restart_guard.get_running_steam_game_pids",
        return_value={},
    ):
        yield
