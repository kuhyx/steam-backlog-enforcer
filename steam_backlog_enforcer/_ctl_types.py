"""Result types returned by :mod:`steam_backlog_enforcer._ctl_client`.

Plain frozen dataclasses so the web server maps them onto its contract types
without ever handling the daemon's raw JSON.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FastInstallInfo:
    """A steam-game-installer run the daemon started, as far as its log tells.

    ``percent`` is the current depot's (``None`` until one is known); ``phase``
    names the depot, e.g. ``downloading depot 3/8``.
    """

    app_id: int
    name: str
    phase: str
    percent: float | None
    elapsed_seconds: int


@dataclass(frozen=True)
class DaemonInfo:
    """The daemon's own account of itself (``status``)."""

    state: str
    started_at: str
    pid: int
    restart_available_at: str | None
    # Empty from a daemon too old to report them.
    fast_installs: tuple[FastInstallInfo, ...] = ()


@dataclass(frozen=True)
class StoreWindow:
    """An opened store window."""

    minutes: int
    until: str


@dataclass(frozen=True)
class BlockResult:
    """A started total gaming block."""

    days: int
    until: str | None


@dataclass(frozen=True)
class PendingReset:
    """An armed two-phase gaming reset (maps onto the contract's PendingAction)."""

    pending_id: str
    phrase: str
    armed_at: str
    ready_at: str
    heartbeat_interval_seconds: int


@dataclass(frozen=True)
class ResetResult:
    """A committed gaming reset."""

    day_key: str
    seconds_before: float
    was_blocked: bool
    released: list[str]
