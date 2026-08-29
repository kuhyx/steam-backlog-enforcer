"""Turning each raw engagement signal into a pause cause.

Split from :mod:`_playtime_engagement`, which owns the per-tick decision and the
backdate; this owns the three probes and the rule each one applies. Every probe
follows the same contract: append to *causes* when the criterion says "not
playing", append to *degraded* when the probe could not answer, and never raise.

**A probe that fails does not pause the tick.** Failure means the tick is billed.
A detector that stopped working must never become an unlimited-gaming exploit,
so the burden of proof sits on "not playing", not on "playing".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._engagement_types import (
    CAUSE_FOCUS,
    CAUSE_IDLE,
    CAUSE_SCREEN_HELD,
    PROBE_FOCUS,
    PROBE_IDLE,
    PROBE_SCREEN_HELD,
    CauseTally,
)
from steam_backlog_enforcer._playtime_kill import (
    _INIT_PID,
    _MAX_PROCESS_TREE_DEPTH,
    _read_ppid,
)
from steam_backlog_enforcer._screen_hold import ScreenHoldError, screen_hold
from steam_backlog_enforcer._x_focus import focused_pid
from steam_backlog_enforcer._x_probe import XProbeError

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer._controller_input import ControllerActivity
    from steam_backlog_enforcer._playtime_state import PlaytimeRules
    from steam_backlog_enforcer._x_probe import XProbe

logger = logging.getLogger(__name__)


def assess_screen(
    holder_path: Path, tally: CauseTally
) -> tuple[bool | None, int | None]:
    """Add the screen-held cause if a gatelock guard owns the display.

    Args:
        holder_path: The gatelock holder lock.
        tally: Accumulating causes and probe failures.

    Returns:
        The hold state and holding PID, both ``None`` when the probe failed.
    """
    try:
        hold = screen_hold(holder_path)
    except ScreenHoldError as exc:
        logger.warning("Screen-hold probe failed; billing this tick: %s", exc)
        tally.degraded.append(PROBE_SCREEN_HELD)
        return None, None

    if hold.held:
        tally.causes.append(CAUSE_SCREEN_HELD)
    return hold.held, hold.holder_pid


def assess_focus(
    probe: XProbe,
    rules: PlaytimeRules,
    qualifying: set[int],
    tally: CauseTally,
) -> int | None:
    """Add the focus cause unless a qualifying process owns the focus.

    Args:
        probe: X connection.
        rules: Policy for this tick.
        qualifying: PIDs that would otherwise count.
        tally: Accumulating causes and probe failures.

    Returns:
        The focused PID, or ``None``.
    """
    if not rules.require_game_focus:
        return None
    try:
        pid = focused_pid(probe.connect())
    except XProbeError as exc:
        logger.warning("Focus probe failed; billing this tick: %s", exc)
        tally.degraded.append(PROBE_FOCUS)
        probe.close()
        return None

    if not focus_qualifies(pid, qualifying):
        tally.causes.append(CAUSE_FOCUS)
    return pid


def assess_idle(
    probe: XProbe,
    controller: ControllerActivity,
    rules: PlaytimeRules,
    tally: CauseTally,
    now_monotonic: float,
) -> tuple[float | None, float | None]:
    """Add the idle cause when every input source has gone quiet.

    The controller is polled first and its age folded in with ``min``: the X
    idle counter does not see a gamepad, and pausing during controller play
    would be the gate's worst failure.

    Args:
        probe: X connection.
        controller: Controller-activity watcher.
        rules: Policy for this tick.
        tally: Accumulating causes and probe failures.
        now_monotonic: Monotonic timestamp for controller ages.

    Returns:
        The effective idle seconds and the controller idle seconds.
    """
    controller.poll(now=now_monotonic)
    controller_idle = controller.seconds_since_activity(now=now_monotonic)

    try:
        pointer_idle = probe.idle_seconds()
    except XProbeError as exc:
        logger.warning("Idle probe failed; billing this tick: %s", exc)
        tally.degraded.append(PROBE_IDLE)
        probe.close()
        return None, controller_idle

    idle = pointer_idle
    if controller_idle is not None:
        idle = min(idle, controller_idle)
    if idle >= rules.idle_grace_seconds:
        tally.causes.append(CAUSE_IDLE)
    return idle, controller_idle


def focus_qualifies(focus_pid: int | None, qualifying: set[int]) -> bool:
    """Whether *focus_pid* is, or descends from, a qualifying process.

    A game's visible window is often owned by a child of the process carrying
    ``SteamAppId`` — Proton in particular — so the ancestry is walked rather
    than compared directly.

    Args:
        focus_pid: PID owning the focused window, or ``None``.
        qualifying: PIDs that count as gaming.

    Returns:
        Whether the focused window belongs to the game.
    """
    if focus_pid is None:
        return False
    pid = focus_pid
    for _ in range(_MAX_PROCESS_TREE_DEPTH):
        if pid in qualifying:
            return True
        if pid <= _INIT_PID:
            return False
        parent = _read_ppid(pid)
        if parent is None:
            return False
        pid = parent
    return False
