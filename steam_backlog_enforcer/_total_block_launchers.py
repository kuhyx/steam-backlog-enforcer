"""Process-name tables for the game launchers a total block kills.

A data table, kept apart from the killing mechanism in
:mod:`steam_backlog_enforcer._total_block_purge` so that adding a launcher
is a one-line data change.
"""

from __future__ import annotations

STEAM_CLIENT_PROCESS_NAMES = frozenset({"steam", "steamwebhelper", "steam.sh"})

# Third-party game launchers, best-effort match by process name.
LAUNCHER_PROCESS_NAMES = frozenset(
    {
        "EpicGamesLauncher",
        "legendary",
        "lutris",
        "heroic",
        "GalaxyClient",
        "itch",
        "bottles",
        "minecraft-launcher",
        "prismlauncher",
        "multimc",
        "polymc",
        "ATLauncher",
        "GDLauncher",
        "gdlauncher-carbon",
        "TLauncher",
        "modrinth-app",
    }
)
# Known limitation, not engineered around in this pass: any launcher run
# via an interpreter rather than its own compiled binary shows up in
# /proc/*/comm as the INTERPRETER's name, not its own - process-name
# matching won't catch those. Confirmed live for "lutris" (a Python
# script, appears as `python3`), and documented upstream for some
# Minecraft launchers (TLauncher, ATLauncher, GDLauncher - exec'd as
# `java -jar ...`, appear as `java`). Matching the interpreter name
# itself is NOT a fix: kill_processes_by_name runs inside this very
# enforcer process, which is itself `python3` - adding it to the set
# would SIGTERM the daemon and every other Python process on the system.
# Consistent with the "best-effort" framing already agreed for non-Steam
# blocking; the hosts+iptables domain blocking below is the backstop for
# launchers this can't catch by process name.
