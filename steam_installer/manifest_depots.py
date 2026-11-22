"""What a manifest finish records about depots and builds, apart from file I/O.

Split out of manifest_write.py (250-line cap).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Proven:
    """The extras a finish may add beyond what the manifest on disk already says.

    ``dlc_depots`` maps a DLC depot to its DLC app id. Steam's own manifests
    record each DLC depot with that ``dlcappid``, so it is written the same way.
    ``build_id``, when given, is a build the caller proved from the cached depot
    manifests; it replaces the one Steam recorded. ``seed`` (from
    :func:`seed_app_state`) is written instead when there is no manifest.
    """

    dlc_depots: dict[str, str] = field(default_factory=dict)
    build_id: str | None = None
    seed: dict | None = None


def pick_buildid(app_state: dict, proven_build: str | None) -> str:
    """The build to record: the proven one, else Steam's, else "0".

    "0" means "no real build installed yet" (Steam uses it as a sentinel) -- a
    bare `or` treats that non-empty string as truthy and never falls through to
    TargetBuildID, leaving a stale/wrong buildid.
    """
    existing = app_state.get("buildid")
    recorded = existing if existing and existing != "0" else None
    return proven_build or recorded or app_state.get("TargetBuildID") or "0"


def installed_depots(
    app_state: dict, depot_manifests: dict[str, str], dlc_depots: dict[str, str]
) -> dict:
    """InstalledDepots for the cached depots, minus the shared ones.

    A shared depot (e.g. Steamworks Common Redistributables) is installed once
    under its owning app and only referenced here. Listing it in
    InstalledDepots as though this app owned a copy contradicts SharedDepots.
    """
    shared = app_state.get("SharedDepots")
    shared_ids = set(shared) if isinstance(shared, dict) else set()
    installed: dict = {}
    for depot_id, manifest_id in depot_manifests.items():
        if depot_id in shared_ids:
            continue
        entry = {"manifest": manifest_id, "size": "0"}
        if depot_id in dlc_depots:
            entry["dlcappid"] = dlc_depots[depot_id]
        installed[depot_id] = entry
    return installed
