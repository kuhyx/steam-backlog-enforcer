"""Errors raised when Steam cannot be driven.

A leaf module so both :mod:`steam_backlog_enforcer.library_hider` and
:mod:`steam_backlog_enforcer._steam_launch` can raise and catch these without
importing each other. Split out to keep both under the 250-line cap.
"""

from __future__ import annotations


class SteamUnavailableError(RuntimeError):
    """Raised when Steam cannot be driven over CDP.

    Covers both "Steam is not installed" and "Steam is installed but never
    opened its debug port". Callers are expected to degrade gracefully rather
    than abort: an unreachable Steam means there is no library to hide, which
    is not a fatal condition for the enforcer.
    """


class SteamUpdateInProgressError(SteamUnavailableError):
    """Raised to defer a Steam restart while a game update is in flight.

    Subclasses :class:`SteamUnavailableError` so existing callers already
    degrade gracefully (skip this pass, retry next loop). Restarting Steam
    mid-update suspends and can corrupt the transfer, so the enforcer waits
    for updates to finish before bouncing Steam to open the CDP port.
    """


class DesktopSessionNotReadyError(SteamUnavailableError):
    """Raised to defer a Steam launch until the user's session exists.

    Subclasses :class:`SteamUnavailableError` so existing callers already
    degrade gracefully (skip this pass, retry next loop). Launching Steam
    before ``/run/user/<uid>`` exists hands every Wine child a runtime dir
    that is not there, so it falls back from winepulse to winealsa and stays
    that way for the whole session — the Kingdom Come: Deliverance II startup
    crash. Waiting a pass costs 3s; getting it wrong costs a reboot.
    """
