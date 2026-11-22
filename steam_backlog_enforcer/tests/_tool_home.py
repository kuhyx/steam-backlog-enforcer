"""Fixture Steam homes for the Steam-tool removal tests.

Builds ``<root>/steamapps``, ``<root>/config/config.vdf`` and
``<root>/compatibilitytools.d`` under a tmp dir, never the real Steam root.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._tool_need import NATIVE_TOOL, STEAM_TOOLS

if TYPE_CHECKING:
    from pathlib import Path


def acf(app_id: int, name: str) -> str:
    """A minimal fully-installed appmanifest."""
    return (
        f'"AppState"\n{{\n\t"appid"\t\t"{app_id}"\n\t"name"\t\t"{name}"\n'
        f'\t"installdir"\t\t"dir{app_id}"\n\t"StateFlags"\t\t"4"\n}}\n'
    )


def config_vdf(mapping: dict[int, str]) -> str:
    """A config.vdf with Steam's real nesting (and its lowercase ``valve``)."""
    entries = "".join(
        f'\t\t\t\t\t"{app_id}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"name"\t\t"{tool}"\n'
        f'\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"250"\n'
        "\t\t\t\t\t}\n"
        for app_id, tool in mapping.items()
    )
    return (
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
        '\t\t\t\t\t"0"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"proton_experimental"\n'
        f"\t\t\t\t\t}}\n{entries}\t\t\t\t}}\n\t\t\t}}\n\t\t}}\n\t}}\n}}\n"
    )


def make_home(
    root: Path,
    games: dict[int, str | None],
    *,
    tools: bool = True,
    toolmanifest: bool = True,
) -> Path:
    """Write a fixture Steam root; return its ``steamapps``.

    Args:
        root: Directory to become the Steam root.
        games: Installed game app id -> its CompatToolMapping tool name, or
            None for a game with no mapping entry.
        tools: Install the three Steam tools (manifest + files).
        toolmanifest: Install proton-cachyos-native's toolmanifest.vdf.
    """
    steamapps = root / "steamapps"
    (steamapps / "common").mkdir(parents=True)
    installed = {app_id: f"Game {app_id}" for app_id in games}
    if tools:
        installed |= STEAM_TOOLS
    for app_id, name in installed.items():
        (steamapps / f"appmanifest_{app_id}.acf").write_text(acf(app_id, name))
        (steamapps / "common" / f"dir{app_id}").mkdir()
        (steamapps / "common" / f"dir{app_id}" / "file.bin").write_text("x")
    (root / "config").mkdir()
    mapping = {app_id: tool for app_id, tool in games.items() if tool}
    (root / "config" / "config.vdf").write_text(config_vdf(mapping))
    if toolmanifest:
        tool_dir = root / "compatibilitytools.d" / NATIVE_TOOL
        tool_dir.mkdir(parents=True)
        (tool_dir / "toolmanifest.vdf").write_text('"manifest"\n{\n}\n')
    return steamapps
