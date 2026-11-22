"""Shared data for the map-installed tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_installer import compat_map, proton_pkg

if TYPE_CHECKING:
    from pathlib import Path

LOCKED = proton_pkg.read_lock().version
CONFIG = (
    '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
    '\t\t\t"Steam"\n\t\t\t{\n\t\t\t}\n\t\t}\n\t}\n}\n'
)
PLAIN = {
    "common": {"name": "Plain", "oslist": "windows", "type": "Game"},
    "depots": {"11": {"config": {"oslist": "windows"}}},
}
NATIVE = {"common": {"name": "Native", "oslist": "windows,linux", "type": "Game"}}
SHARED = {
    "common": {"name": "Shared", "oslist": "windows", "type": "Game"},
    "depots": {"31": {"depotfromapp": "228980"}},
}
CS = {"common": {"name": "CS", "oslist": "windows,linux", "type": "Game"}}
TOOL = {"common": {"name": "Proton Experimental", "type": "Tool"}}


def _mapped(root: Path, appid: int) -> tuple[str, str] | None:
    return compat_map.current(root / "config" / "config.vdf", appid)
