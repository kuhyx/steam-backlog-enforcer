"""Desktop notifications for the playtime budget, and time formatting.

Notifications must reach the logged-in desktop session, not the root systemd
context the enforcer runs in, which is why they are dispatched through
``_run_as_user``.
"""

from __future__ import annotations

import logging

from steam_backlog_enforcer.library_hider import _resolve_desktop_user, _run_as_user

logger = logging.getLogger(__name__)

_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


def notify_desktop_user(title: str, body: str) -> None:
    """Send a desktop notification into the real user's session.

    ``enforcer.send_notification`` runs ``notify-send`` as root with no
    ``DBUS_SESSION_BUS_ADDRESS``, which cannot reach the user's session bus from
    a system service. This routes through the same ``sudo -u <user> env ...``
    mechanism that ``library_hider`` uses to launch Steam.

    Args:
        title: Notification title.
        body: Notification body.
    """
    user = _resolve_desktop_user()
    try:
        _run_as_user(["notify-send", title, body, "--icon=dialog-warning"], user)
    except (OSError, ValueError):
        logger.debug("Could not send desktop notification.")


def _humanise(seconds: int) -> str:
    """Render a warning threshold as a short human phrase.

    Args:
        seconds: Seconds remaining.

    Returns:
        A phrase such as ``"30 minutes"`` or ``"10 seconds"``.
    """
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds} seconds"
    minutes = seconds // _SECONDS_PER_MINUTE
    return "1 hour" if minutes == _MINUTES_PER_HOUR else f"{minutes} minutes"
