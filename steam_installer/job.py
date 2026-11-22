"""Everything one install run is about, bundled so it travels as one argument."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from steam_installer import appinfo, takeover
    from steam_installer.library import SteamLibrary


@dataclass(frozen=True)
class Job:
    """The app, where it goes, what Steam already staged, and as whom."""

    library: SteamLibrary
    metadata: appinfo.AppMetadata
    install_target: Path
    staged: takeover.Staged | None
    username: str
    language: str
