"""One daemon pass under a total block: the research window or the full block.

The enforce loop hands its whole total-block branch here. With a research
window open (see :mod:`steam_backlog_enforcer._research_window`) Steam is left
installed and reachable, and the *only* thing kept is the one-allowed-game
rule, bent to a single game: the loop-local allowed set is ``{Librarian}``. The
real assignment in ``state.json`` is never read or written, so there is
nothing to restore afterwards. Everything else the block does to Steam itself
(kill, uninstall, purge) is skipped while the window is open.

Once the deadline (the extension's, if the window was extended) passes, the
record is latched closed (a clock set back cannot reopen it) and every pass is
the ordinary :func:`enforce_total_block_tick` again: it kills Steam, removes the
package, rebuilds the firewall chain from the kept IP cache, and puts the full
hosts section back. The purge spares ``~/.local/share/Steam`` for the rest of
the lock (Librarian's install and saves stay), and since that install could
otherwise be launched without the package, every Steam game is killed on sight.
The lock's end date is never involved.
"""

from __future__ import annotations

from dataclasses import replace
import logging
import subprocess
from typing import TYPE_CHECKING

from leisure_watch.procscan import LAUNCHER_PROCESS_NAMES, kill_target_names

from steam_backlog_enforcer import _research_net as net
from steam_backlog_enforcer import _research_window as window
from steam_backlog_enforcer import config as config_module
from steam_backlog_enforcer._enforce_guards import guard_installed_games
from steam_backlog_enforcer._research_net import reconcile_open_window
from steam_backlog_enforcer._steam_launch import steam_is_installed
from steam_backlog_enforcer._total_block import enforce_total_block_tick
from steam_backlog_enforcer._total_block_purge import kill_and_uninstall_launchers
from steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    kill_processes_by_name,
    send_notification,
)
from steam_backlog_enforcer.store_blocker import restore_store_block

if TYPE_CHECKING:
    from steam_backlog_enforcer._research_record import ResearchRecord
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)


def _latch_closed(record: ResearchRecord) -> ResearchRecord:
    """Persist that the window is over; blocking does not wait for the write."""
    closed = replace(record, closed=True)
    try:
        window.write_record(closed)
    except OSError:
        logger.exception("Could not latch the research window closed")
    return closed


def _reblock_store(config: Config, record: ResearchRecord) -> None:
    """Put the normal store block back once, after the window ended.

    The total block's own hosts section covers the store until the lock ends,
    but ``end_total_block_cleanup`` does not restore the normal block, so
    without this the store would stay open after the lock. Unconditional
    (:func:`restore_store_block`): the section being back makes the store look
    blocked already.
    """
    if not net.attempt_due("store"):
        return
    if config.block_store and not restore_store_block():
        net.note_failure("store")
        return
    try:
        window.write_record(replace(record, store_reblocked=True))
    except OSError:
        logger.exception("Could not record that the store block is back")


def _research_pass(record: ResearchRecord) -> None:
    """Keep Steam open and Librarian the only game while the window is open."""
    reconcile_open_window(record)
    # Non-Steam launchers and counted games are still forbidden; Steam itself
    # is not killed, uninstalled or purged (that is the block's tick).
    kill_and_uninstall_launchers(LAUNCHER_PROCESS_NAMES)
    kill_processes_by_name(kill_target_names(config_module.CONFIG_FILE))
    if not steam_is_installed():
        return
    allowed = {window.LIBRARIAN_APP_ID}
    _kill_games_except(allowed)
    guard_installed_games(allowed, strict=True)


def _kill_games_except(allowed: set[int]) -> None:
    """Kill every running Steam game outside *allowed* (runtimes excepted)."""
    for _pid, app_id in enforce_allowed_game(
        allowed, kill_unauthorized=True, strict=True
    ):
        send_notification("⛔🎮", f"{app_id} → 🎯 {window.LIBRARIAN_NAME}")


def total_block_pass(config: Config) -> None:
    """The total-block branch of one enforce pass.

    Args:
        config: Loaded configuration (``block_store`` gates the store re-block).
    """
    at = window.now()
    record = window.live_record(at)
    if record is not None and record.is_open(at):
        # A loaded machine can push pacman/iptables past their timeouts; that
        # costs this tick (the next one retries), never the daemon.
        try:
            _research_pass(record)
        except OSError, subprocess.SubprocessError:
            logger.exception("Research window pass failed; retrying next tick")
        return
    if record is not None and not record.closed and at >= record.ends_at:
        record = _latch_closed(record)
    # Used window (or a record that cannot say): the Steam folder is kept, and
    # so no Steam game may run from it. {0} only makes the allowed set non-empty;
    # app 0 is the client itself, which the block's own tick kills by name.
    used = record is not None or window.research_used(at)
    enforce_total_block_tick(keep_steam_dir=used)
    if used:
        _kill_games_except({0})
    if record is not None and record.closed and not record.store_reblocked:
        _reblock_store(config, record)
