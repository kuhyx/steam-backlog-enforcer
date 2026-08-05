"""Look up app metadata via steamcmd's app_info_print (anonymous, no login needed)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

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

    @property
    def all_expected(self) -> set[str]:
        return self.required | self.shared


def _fetch_app_block(appid: int) -> dict:
    result = subprocess.run(
        [
            "steamcmd",
            # Without this, a Linux steamcmd resolves a Windows-only app's depot
            # list against the host platform and can come back empty.
            "+@sSteamCmdForcePlatformType",
            "windows",
            "+login",
            "anonymous",
            "+app_info_print",
            str(appid),
            "+quit",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout
    # app_info_print emits `"<appid>"\n{ ... }` inside a stream of steamcmd's own log lines;
    # slice from the first line that starts the VDF block onward.
    match = re.search(rf'^"{appid}"\s*$', output, re.MULTILINE)
    if not match:
        raise AppInfoError(f"steamcmd did not return app info for {appid}:\n{output}")
    data = vdf.parse(output[match.start() :])
    app_block = data.get(str(appid), {})
    if not isinstance(app_block, dict):
        raise AppInfoError(f"unexpected app_info_print structure for {appid}")
    return app_block


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

    required: set[str] = set()
    shared: set[str] = set()
    for depot_id, entry in depots.items():
        if not depot_id.isdigit() or not isinstance(entry, dict):
            continue
        # A shared depot is installed once under its owning app, not here.
        if "depotfromapp" in entry or "sharedinstall" in entry:
            shared.add(depot_id)
            continue
        if entry.get("dlcappid") or entry.get("optional") == "1":
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
