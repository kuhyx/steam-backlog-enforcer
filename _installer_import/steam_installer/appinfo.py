"""Look up app metadata via steamcmd's app_info_print (anonymous, no login needed)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

from steam_installer import vdf


class AppInfoError(Exception):
    pass


@dataclass
class AppMetadata:
    appid: int
    name: str
    installdir: str


@dataclass
class DepotPlan:
    """Which depots a given (os, language) install is actually supposed to contain.

    Needed to check that a download finished. "Every depot in app_info" is the
    wrong bar: KCD2 lists 12 depots but an english/windows install only ever
    fetches 3 of them, the rest being other languages, DLC and other platforms.
    """

    required: set[str]
    shared: set[str]
    # depot id -> the DLC app it belongs to. Steam writes that dlcappid into
    # InstalledDepots, and a DLC depot recorded without it is not credited.
    dlc: dict[str, str] = field(default_factory=dict)

    @property
    def all_expected(self) -> set[str]:
        return self.required | self.shared


def _fetch_app_blocks(appids: list[int]) -> dict[int, dict]:
    """App info for every id in `appids`, from a single anonymous steamcmd call.

    One call for the lot: each steamcmd start costs seconds of login, and a game
    can list dozens of DLC.
    """
    prints = [arg for appid in appids for arg in ("+app_info_print", str(appid))]
    result = subprocess.run(
        [
            "steamcmd",
            # Without this, a Linux steamcmd resolves a Windows-only app's depot
            # list against the host platform and can come back empty.
            "+@sSteamCmdForcePlatformType",
            "windows",
            "+login",
            "anonymous",
            *prints,
            "+quit",
        ],
        capture_output=True,
        text=True,
        # The exit code says nothing useful; a missing block is caught below.
        check=False,
        timeout=60 + 5 * len(appids),
    )
    output = result.stdout
    # app_info_print emits `"<appid>"\n{ ... }` inside a stream of steamcmd's own
    # log lines; each block runs from its own header to the next one.
    starts = {}
    for appid in appids:
        match = re.search(rf'^"{appid}"\s*$', output, re.MULTILINE)
        if not match:
            raise AppInfoError(
                f"steamcmd did not return app info for {appid}:\n{output}"
            )
        starts[appid] = match.start()
    ordered = sorted(starts.values()) + [len(output)]
    blocks: dict[int, dict] = {}
    for appid, start in starts.items():
        end = ordered[ordered.index(start) + 1]
        app_block = vdf.parse(output[start:end]).get(str(appid), {})
        if not isinstance(app_block, dict):
            raise AppInfoError(f"unexpected app_info_print structure for {appid}")
        blocks[appid] = app_block
    return blocks


def _fetch_app_block(appid: int) -> dict:
    return _fetch_app_blocks([appid])[appid]


def get_metadata(appid: int) -> AppMetadata:
    """Fetch the fields this project actually needs: display name and installdir."""
    app_block = _fetch_app_block(appid)
    common = app_block.get("common", {})
    if not isinstance(common, dict):
        raise AppInfoError(f"no 'common' section in app info for {appid}")

    name = common.get("name")
    if not isinstance(name, str):
        raise AppInfoError(f"no name field found for app {appid}")

    installdir = common.get("installdir")
    if not isinstance(installdir, str):
        config = app_block.get("config", {})
        installdir = config.get("installdir") if isinstance(config, dict) else None
    if not isinstance(installdir, str):
        raise AppInfoError(f"no installdir field found for app {appid}")

    return AppMetadata(appid=appid, name=name, installdir=installdir)


def get_build_id(appid: int, branch: str = "public") -> str | None:
    """Current buildid for `branch`, used to sanity-check the manifest we write."""
    app_block = _fetch_app_block(appid)
    depots = app_block.get("depots", {})
    if not isinstance(depots, dict):
        return None
    branches = depots.get("branches", {})
    if not isinstance(branches, dict):
        return None
    entry = branches.get(branch, {})
    if not isinstance(entry, dict):
        return None
    build_id = entry.get("buildid")
    return build_id if isinstance(build_id, str) else None


def get_depot_plan(
    appid: int, language: str = "english", os_name: str = "windows"
) -> DepotPlan:
    """Depots an (os, language) install should end up with.

    Skips depots belonging to another language, another OS, a DLC (`dlcappid`)
    or marked `optional` -- none of those are fetched by a default install, so
    demanding them would make a healthy download look incomplete.
    """
    app_block = _fetch_app_block(appid)
    depots = app_block.get("depots", {})
    if not isinstance(depots, dict):
        raise AppInfoError(f"no 'depots' section in app info for {appid}")
    plan = _plan_from_depots(appid, depots, language, os_name)
    # Tag the game's own list's DLC depots too: depotdownloader fetches the
    # owned ones in the base run, and Steam records each with its dlcappid.
    for depot_id, entry in depots.items():
        if isinstance(entry, dict) and isinstance(entry.get("dlcappid"), str):
            plan.dlc[depot_id] = entry["dlcappid"]
    return plan


def get_dlc_plans(
    appid: int, language: str = "english", os_name: str = "windows"
) -> dict[int, set[str]]:
    """DLC app id -> the depots it installs itself, for DLC with depots of its own.

    Some DLC (Cyberpunk 2077's Phantom Liberty, app 2138330, ~25 GB) keeps its
    content under its own app id rather than in the game's depot list, so a
    depotdownloader run for the game never sees it. DLC with no depots of its
    own, or whose depots the game already lists, needs no run of its own.
    """
    app_block = _fetch_app_block(appid)
    extended = app_block.get("extended", {})
    listed = extended.get("listofdlc", "") if isinstance(extended, dict) else ""
    dlc_ids = [int(x) for x in str(listed).split(",") if x.strip().isdigit()]
    if not dlc_ids:
        return {}
    game_depots = app_block.get("depots", {})
    game_depot_ids = set(game_depots) if isinstance(game_depots, dict) else set()
    plans: dict[int, set[str]] = {}
    for dlc_id, dlc_block in _fetch_app_blocks(dlc_ids).items():
        depots = dlc_block.get("depots", {})
        if not isinstance(depots, dict):
            continue
        own = _plan_from_depots(dlc_id, depots, language, os_name).required
        own -= game_depot_ids
        if own:
            plans[dlc_id] = own
    return plans


def _plan_from_depots(
    appid: int, depots: dict, language: str, os_name: str
) -> DepotPlan:
    """The depots of one app's `depots` section that an (os, language) install gets."""
    required: set[str] = set()
    shared: set[str] = set()
    for depot_id, entry in depots.items():
        if not depot_id.isdigit() or not isinstance(entry, dict):
            continue
        # A shared depot is installed once under its owning app, not here.
        if "depotfromapp" in entry or "sharedinstall" in entry:
            shared.add(depot_id)
            continue
        # Another app's DLC is not part of this install -- but a DLC app's own
        # depots carry its own id as dlcappid, and are exactly what it installs.
        dlc_owner = entry.get("dlcappid")
        if (dlc_owner and dlc_owner != str(appid)) or entry.get("optional") == "1":
            continue
        config = entry.get("config", {})
        config = config if isinstance(config, dict) else {}
        oslist = config.get("oslist")
        if isinstance(oslist, str) and oslist and os_name not in oslist.split(","):
            continue
        depot_language = config.get("language")
        if isinstance(depot_language, str) and depot_language != language:
            continue
        required.add(depot_id)
    return DepotPlan(required=required, shared=shared)
