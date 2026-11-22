"""Manifest helpers for tests that need a Steam library on disk."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_installer import vdf

if TYPE_CHECKING:
    from pathlib import Path

    from steam_installer.library import SteamLibrary


GHOST_ACF = """"AppState"
{
\t"appid"\t\t"284160"
\t"universe"\t\t"1"
\t"name"\t\t"BeamNG.drive"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"BeamNG.drive"
\t"LastUpdated"\t\t"0"
\t"SizeOnDisk"\t\t"0"
\t"StagingSize"\t\t"0"
\t"buildid"\t\t"24617469"
\t"DownloadType"\t\t"1"
\t"BytesToDownload"\t\t"0"
\t"BytesDownloaded"\t\t"0"
\t"TargetBuildID"\t\t"24617469"
\t"InstalledDepots"
\t{
\t}
\t"UserConfig"
\t{
\t\t"language"\t\t"english"
\t}
}
"""


def _write(library: SteamLibrary, appid: int, text: str) -> Path:
    path = library.steamapps / f"appmanifest_{appid}.acf"
    path.write_text(text)
    return path


def _real_install(
    library: SteamLibrary,
    appid: int = 475150,
    installdir: str = "RealGame",
    size: str = "13908166765",
) -> Path:
    """A manifest shaped like the genuinely installed apps in a live library."""
    _write(
        library,
        appid,
        vdf.dumps(
            "AppState",
            {
                "appid": str(appid),
                "StateFlags": "4",
                "installdir": installdir,
                "SizeOnDisk": size,
                "InstalledDepots": {"475151": {"manifest": "123"}},
            },
        ),
    )
    content = library.common / installdir
    content.mkdir(parents=True, exist_ok=True)
    (content / "game.pak").write_bytes(b"x" * 4096)
    return content


def stamp_native_tool(root: Path, version: str) -> None:
    """Put a ready native Proton (manifest and version stamp) under *root*."""
    tool = root / "compatibilitytools.d" / "proton-cachyos-native"
    tool.mkdir(parents=True)
    (tool / "toolmanifest.vdf").write_text("x")
    (tool / "VERSION").write_text(version + "\n")
