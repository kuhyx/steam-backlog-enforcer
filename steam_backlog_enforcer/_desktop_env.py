"""Environment handed to processes launched into the user's desktop session.

The enforcer runs as root under systemd, so anything it starts on the desktop
user's behalf goes through ``sudo -u <user> env ...``. ``sudo`` resets the
environment, which makes the list below an *allowlist*: every variable the
desktop session needs must be named here explicitly, and every omission fails
silently rather than erroring.

Lives in its own module (like ``_steam_state``) so both ``library_hider`` and
``game_install`` can share one builder without forming an import cycle.

``XDG_RUNTIME_DIR`` is load-bearing and was missing here for a long time.
Without it Wine cannot reach ``$XDG_RUNTIME_DIR/pulse/native``, silently falls
back from ``winepulse.drv`` to ``winealsa.drv``, and every Proton game gets raw
ALSA devices instead of the session's PulseAudio sink. That crashed Kingdom
Come: Deliverance II during its startup video, and looked like a corrupt
install because restarting Steam by hand - the thing a reinstall incidentally
does - was what actually cleared it.

Only ``XDG_RUNTIME_DIR`` is exported for audio, deliberately: pressure-vessel
reads it to bind-mount the pulse socket into the Steam Linux Runtime container,
whereas a hardcoded ``PULSE_SERVER=unix:/run/user/<uid>/pulse/native`` would
name a *host* path that need not resolve inside that container.
"""

from __future__ import annotations

import os
from pathlib import Path


def desktop_runtime_dir(uid: int) -> str:
    """Path to the desktop user's XDG runtime directory."""
    return f"/run/user/{uid}"


def desktop_session_ready(uid: int) -> bool:
    """Whether the desktop user's runtime directory exists yet.

    The enforcer is a system service ordered only ``After=network-online``,
    while ``/run/user/<uid>`` is created by ``user-runtime-dir@<uid>.service``
    when logind opens the session. On a cold boot the enforcer can reach its
    first launch before that directory exists — measured on one boot, it
    started 54ms *before* the runtime-dir unit and only won by doing other
    work first.

    A Steam launched in that window would name a runtime dir that is not
    there, which is exactly the winealsa fallback this module exists to
    prevent, and it would stay broken for the whole session. Callers gate on
    this and retry on the next enforce pass instead.
    """
    return Path(desktop_runtime_dir(uid)).is_dir()


def desktop_env_args(user: str, uid: int) -> list[str]:
    """Build the ``env`` arguments for a command run as the desktop *user*.

    Session paths are derived from *uid* rather than read from the current
    environment: the enforcer normally runs as root, and inheriting root's
    ``XDG_RUNTIME_DIR`` would point the child at ``/run/user/0``, which it
    cannot use.
    """
    runtime_dir = desktop_runtime_dir(uid)
    dbus_default = f"unix:path={runtime_dir}/bus"
    dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", dbus_default)
    xauth = os.environ.get("XAUTHORITY", f"/home/{user}/.Xauthority")
    return [
        f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
        f"XAUTHORITY={xauth}",
        f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
        f"XDG_RUNTIME_DIR={runtime_dir}",
    ]
