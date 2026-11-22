"""Steam library discovery: find install roots and where a given app lives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from steam_installer import vdf

DEFAULT_STEAM_ROOT = Path.home() / ".local/share/Steam"


@dataclass
class SteamLibrary:
    """One Steam library folder."""

    path: Path

    @property
    def common(self) -> Path:
        """Folder holding installed games."""
        return self.path / "steamapps" / "common"

    @property
    def steamapps(self) -> Path:
        """The library's ``steamapps`` folder."""
        return self.path / "steamapps"


def find_steam_root() -> Path:
    """Locate the Steam installation. Raises if none of the usual paths exist."""
    for candidate in (DEFAULT_STEAM_ROOT, Path.home() / ".steam/steam"):
        if (candidate / "steamapps").is_dir():
            return candidate
    msg = "No Steam installation found at ~/.local/share/Steam or ~/.steam/steam"
    raise FileNotFoundError(msg)


def list_libraries(steam_root: Path) -> list[SteamLibrary]:
    """Every Steam library folder in libraryfolders.vdf, plus steam_root itself."""
    libraries = [SteamLibrary(steam_root)]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf_path.is_file():
        return libraries
    data = vdf.parse(vdf_path.read_text())
    folders = data.get("libraryfolders", {})
    if not isinstance(folders, dict):
        return libraries
    seen = {steam_root.resolve()}
    for entry in folders.values():
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("path")
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        if path not in seen:
            seen.add(path)
            libraries.append(SteamLibrary(path))
    return libraries


def find_existing_install(
    libraries: list[SteamLibrary], installdir: str
) -> Path | None:
    """Return the install path if `installdir` already exists in any library."""
    for library in libraries:
        candidate = library.common / installdir
        if candidate.is_dir():
            return candidate
    return None


def pick_install_target(libraries: list[SteamLibrary], installdir: str) -> Path:
    """Where to install: an existing partial install, else the primary library."""
    existing = find_existing_install(libraries, installdir)
    if existing is not None:
        return existing
    return libraries[0].common / installdir
