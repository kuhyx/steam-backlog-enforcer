"""What a leisure kill never signals, whatever ``now.json`` says.

Defence in depth: ``now.json`` is signed but a determined forger (or a watcher
bug) could name any pid, and the enforcer is root. The desktop session -- the
window manager and its bar, X, the user's systemd and bus, audio, ssh/gpg
agents, multiplexers, terminals and shells, sudo, Claude, the password manager,
the notification daemon, and every locker or accountant -- survives that.

Matched on the binary actually run (the ``exe`` link, never ``comm``, which any
process may rename) or, for a Python interpreter, the script/module it runs.
:mod:`_leisure_kill` asks :func:`never_kill` after :func:`is_protected`.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Final

from steam_backlog_enforcer._leisure_procs import (
    LOCKER_NAMES,
    argv,
    exe_name,
    exe_path,
    script_of,
)

_TERMINALS: Final = frozenset(
    {
        "alacritty",
        "foot",
        "footclient",
        "ghostty",
        "gnome-terminal",
        "gnome-terminal-server",
        "kitty",
        "konsole",
        "lxterminal",
        "mate-terminal",
        "qterminal",
        "rxvt",
        "sakura",
        "st",
        "terminator",
        "terminology",
        "tilix",
        "urxvt",
        "urxvtd",
        "uxterm",
        "wezterm",
        "wezterm-gui",
        "xfce4-terminal",
        "xterm",
    }
)
# Exact exe basenames (lower-case: ``exe_name`` lowers ``Xorg``).
NEVER_KILL_NAMES: Final = _TERMINALS | frozenset(
    {
        "i3",
        "i3bar",
        "i3blocks",
        "xorg",
        "xwayland",
        "systemd",
        "wireplumber",
        "pulseaudio",
        "sshd",
        "ssh-agent",
        "gpg-agent",
        "tmux",
        "screen",
        "zsh",
        "bash",
        "fish",
        "sh",
        "dash",
        "sudo",
        "keepassxc",
        "dunst",
        "xfce4-notifyd",
        "claude",
    }
)
NEVER_KILL_PREFIXES: Final = ("dbus-", "pipewire", "systemd-")
# Python programs by script/module stem: Python terminals, and every locker,
# accountant and the limits bar (LOCKER_NAMES already spares their children).
NEVER_KILL_SCRIPTS: Final = LOCKER_NAMES | frozenset(
    {"daily_limits", "guake", "terminator"}
)
_CLAUDE: Final = "claude"
# Claude Code's native build: ~/.local/share/claude/versions/<version>.
_CLAUDE_DIRS: Final = frozenset({"claude", "claude-code"})
_JS_RUNTIMES: Final = frozenset({"node", "bun"})


def _is_claude(pid: int, name: str) -> bool:
    if _CLAUDE_DIRS & set(PurePath(exe_path(pid).lower()).parts):
        return True
    if name not in _JS_RUNTIMES:
        return False
    script = argv(pid)[1:2]
    return bool(script) and bool(_CLAUDE_DIRS & set(PurePath(script[0]).parts))


def never_kill(pid: int) -> str | None:
    """Why *pid* is never signalled by a leisure kill, ``None`` if it may be.

    Args:
        pid: Candidate process (already past :func:`is_protected`).

    Returns:
        The protected name that matched (for the refusal log), or ``None``.
    """
    name = exe_name(pid)
    if name in NEVER_KILL_NAMES or name.startswith(NEVER_KILL_PREFIXES):
        return name
    if _is_claude(pid, name):
        return _CLAUDE
    script = script_of(pid)
    if script is not None and script[0] in NEVER_KILL_SCRIPTS:
        return script[0]
    return None
