"""Decide per game whether Steam may run it on the native Proton.

Only a game this can prove safe is mapped: Windows-only (the app, every depot
and every launch option), no shared depots, no owned DLC depot, not in the
anti-cheat list, not overridden. Anything else keeps Valve's default, so
Valve's tools come back while that game is installed -- every game stays
playable. When unsure, the answer is no.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

OVERRIDES = Path(__file__).parent / "data" / "compat_overrides.json"


@dataclass
class Decision:
    appid: int
    reasons: list[str] = field(default_factory=list)

    @property
    def map(self) -> bool:
        return not self.reasons

    def describe(self) -> str:
        return "map" if self.map else f"Valve default: {', '.join(self.reasons)}"


def load_overrides(path: Path = OVERRIDES) -> dict[str, str]:
    """`{appid: reason}` for games that break on the native build."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not all(
        key.isdigit() and isinstance(reason, str) for key, reason in data.items()
    ):
        raise ValueError(f"{path.name}: compat_overrides must map app ids to reasons")
    return data


def tool_ready(tool_dir: Path, pinned_version: str) -> bool:
    """The tool is there and is the exact pinned, verified build."""
    stamp = tool_dir / "VERSION"
    return (
        (tool_dir / "toolmanifest.vdf").is_file()
        and stamp.is_file()
        and stamp.read_text().strip() == pinned_version
    )


def _oses(value: object) -> set[str]:
    return {os for os in value.split(",") if os} if isinstance(value, str) else set()


def _dicts(section: object) -> list[dict]:
    if not isinstance(section, dict):
        return []
    return [entry for entry in section.values() if isinstance(entry, dict)]


def _config_oslist(entry: dict) -> set[str]:
    config = entry.get("config")
    return _oses(config.get("oslist")) if isinstance(config, dict) else set()


def _platform_reasons(block: dict) -> list[str]:
    common = block.get("common")
    app_oses = _oses(common.get("oslist")) if isinstance(common, dict) else set()
    depots = _dicts(block.get("depots"))
    config = block.get("config")
    launches = _dicts(config.get("launch")) if isinstance(config, dict) else []
    oses = app_oses.union(*(_config_oslist(e) for e in depots + launches))
    reasons = []
    if not app_oses:
        reasons.append("no OS list")
    if "linux" in oses:
        reasons.append("native")
    if oses - {"windows", "linux"}:
        reasons.append("not Windows-only")
    if any("depotfromapp" in d or "sharedinstall" in d for d in depots):
        reasons.append("shared depots")
    return reasons


def decide(
    appid: int,
    block: dict,
    *,
    anticheat: set[int] | None,
    overrides: dict[str, str],
    owned_dlc: bool,
    tool_ready: bool,
) -> Decision:
    """Every reason `appid` must keep Valve's default; none means map it."""
    reasons: list[str] = []
    if anticheat is None:
        reasons.append("anti-cheat list unavailable")
    elif appid in anticheat:
        reasons.append("anti-cheat")
    reasons += _platform_reasons(block)
    if owned_dlc:
        reasons.append("owned DLC")
    if str(appid) in overrides:
        reasons.append(f"override: {overrides[str(appid)]}")
    if not tool_ready:
        reasons.append("native Proton not installed")
    return Decision(appid, reasons)
