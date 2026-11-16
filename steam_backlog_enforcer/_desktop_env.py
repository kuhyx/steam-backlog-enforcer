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
import pwd
import re

# Where local X servers put their sockets: fixed by libX11, not a scratch file
# (pyproject waives S108 for this module). A module constant so tests (and
# repro scripts) can point it at a scratch directory.
X_SOCKET_DIR = "/tmp/.X11-unix"
# ``:0``, ``:1.0`` and ``unix:0`` are local; ``host:0`` is not.
_LOCAL_DISPLAY = re.compile(r"(?:unix)?:(\d+)(?:\.\d+)?")


def desktop_display() -> str:
    """The X display for the desktop session: inherited, else the usual ``:0``."""
    return os.environ.get("DISPLAY") or ":0"


def x_display_error() -> str | None:
    """Why a program launched now has no X display to open, or ``None``.

    A Steam started without a reachable display logs "Unable to open X11
    display" and exits within seconds, so launching it is pointless. A web
    job (a user unit with no ``DISPLAY``) hit exactly that. Only local
    displays are checked, by their socket: a ``host:N`` display cannot be
    probed without connecting, so it is assumed up.
    """
    display = desktop_display()
    match = _LOCAL_DISPLAY.fullmatch(display)
    if match is None:
        return None
    socket = Path(X_SOCKET_DIR) / f"X{match[1]}"
    if socket.exists():
        return None
    origin = "DISPLAY" if os.environ.get("DISPLAY") else "DISPLAY unset, default"
    return f"No X display for Steam: {origin} {display} is not up ({socket} missing)"


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
        f"DISPLAY={desktop_display()}",
        f"XAUTHORITY={xauth}",
        f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
        f"XDG_RUNTIME_DIR={runtime_dir}",
        # Steam Runtime's srt-logger opts INTO the journal when it finds one
        # (it inherits this unit's JOURNAL_STREAM), regardless of the DEVNULL
        # stderr the spawn already uses. That wrote 481k "joystick FFB" lines
        # in one boot and evicted two weeks of history from a 300M journal.
        # Steam still keeps its own logs/console-linux.txt; this only stops
        # the copy into journald.
        "SRT_LOGGER_USE_JOURNAL=0",
        # SDL3's HIDAPI lg4ff driver has no effect-status query; BeamNG 0.39
        # native treats the failed query as a dead effect and the G29 goes
        # limp (12k "Failed to get joystick3 FFB effect status" lines per
        # session). Narrow hint so gamepads keep HIDAPI (rumble/LEDs); only
        # the Logitech wheel falls back to the kernel driver. Name verified
        # against BeamNG's SDL 3.4.12 strings, 2026-09-14.
        "SDL_JOYSTICK_HIDAPI_LG4FF=0",
    ]


def desktop_uid(user: str | None) -> int:
    """Resolve *user* to a uid, defaulting to the usual first desktop uid."""
    if user:
        try:
            return pwd.getpwnam(user).pw_uid
        except KeyError:
            pass
    return 1000


def resolve_desktop_user() -> str | None:
    """Resolve which desktop user owns the Steam/X11 session.

    Prefers the explicit STEAM_ENFORCER_DESKTOP_USER (set by the systemd
    unit, which has no SUDO_USER/USER of its own since it is started
    directly by systemd rather than via `sudo`), then falls back to
    SUDO_USER/USER for interactive `sudo` invocations.
    """
    return (
        os.environ.get("STEAM_ENFORCER_DESKTOP_USER")
        or os.environ.get("SUDO_USER")
        or os.environ.get("USER")
    )


def _process_owner() -> str | None:
    """The user this process runs as, or ``None`` without a passwd entry."""
    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        return None


def desktop_user_cmd(cmd: list[str], user: str | None) -> list[str]:
    """Wrap *cmd* so it runs in the desktop session as *user*.

    As root: prefixes ``sudo -u <user> env <session vars>``, or returns *cmd*
    unchanged when no desktop user resolves. Unprivileged (a web job): there
    is no one to switch to, but the session vars are still prefixed with a
    plain ``env`` — a user unit has no ``DISPLAY``, and a bare ``steam`` then
    dies with "Unable to open X11 display". The uid comes from the process
    itself, not from the lookup that falls back to 1000.

    This is argv construction only — deliberately no ``subprocess`` call, so
    every spawn site stays in a module covered by the test suite's
    ``_no_subprocess`` guard.
    """
    euid = os.geteuid()
    if euid == 0:
        if user and user != "root":
            return [
                "sudo",
                "-u",
                user,
                "env",
                *desktop_env_args(user, desktop_uid(user)),
                *cmd,
            ]
        return cmd
    owner = user or _process_owner()
    if owner is None:
        return cmd
    return ["env", *desktop_env_args(owner, euid), *cmd]
