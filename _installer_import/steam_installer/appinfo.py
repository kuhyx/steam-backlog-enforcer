"""App metadata (name, installdir, depots, build) from Steam's local app cache."""

from __future__ import annotations

from dataclasses import dataclass, field

from steam_installer import appinfo_cache


# depotdownloader is never given -branch, so it always fetches this one.
PUBLIC_BRANCH = "public"


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
    # depot id -> the manifest gid the public branch ships, for every depot in
    # the app's list. A cached depot manifest matching it proves the build.
    manifests: dict[str, str] = field(default_factory=dict)
    # shared depot id -> the app it is installed under (its `depotfromapp`).
    # A manifest written from scratch records these as SharedDepots.
    shared_owner: dict[str, str] = field(default_factory=dict)

    @property
    def all_expected(self) -> set[str]:
        return self.required | self.shared


def _cached_blocks(appids: list[int]) -> dict[int, dict]:
    """App info for those of `appids` Steam's local cache holds.

    Read from `appcache/appinfo.vdf` (see :mod:`appinfo_cache`), not from
    steamcmd: this tool no longer runs steamcmd at all.
    """
    try:
        apps = appinfo_cache.load()
    except appinfo_cache.CacheError as exc:
        raise AppInfoError(str(exc)) from exc
    return {appid: apps[appid] for appid in appids if appid in apps}


def _fetch_app_blocks(appids: list[int]) -> dict[int, dict]:
    """App info for every id in `appids`; a missing one is an error with the fix."""
    blocks = _cached_blocks(appids)
    missing = [str(appid) for appid in appids if appid not in blocks]
    if missing:
        raise AppInfoError(
            f"app {', '.join(missing)} is not in Steam's local app cache: "
            f"{appinfo_cache.FIX}"
        )
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
        gid = _public_gid(entry)
        if gid is not None:
            plan.manifests[depot_id] = gid
    return plan


def _public_gid(entry: object) -> str | None:
    """The manifest gid a depot ships on the public branch, if it ships one."""
    manifests = entry.get("manifests") if isinstance(entry, dict) else None
    public = manifests.get(PUBLIC_BRANCH) if isinstance(manifests, dict) else None
    gid = public.get("gid") if isinstance(public, dict) else None
    return gid if isinstance(gid, str) else None


def get_dlc_plans(
    appid: int, language: str = "english", os_name: str = "windows"
) -> dict[int, dict[str, str]]:
    """DLC app id -> {depot: public gid} it installs itself, for DLC with depots
    of its own.

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
    plans: dict[int, dict[str, str]] = {}
    # A DLC the cache lacks is not owned: Steam caches app info for every app
    # the account owns (1828 of 7102 listed DLC ids on 2026-11-22), and
    # depotdownloader would refuse an unowned one anyway.
    for dlc_id, dlc_block in _cached_blocks(dlc_ids).items():
        depots = dlc_block.get("depots", {})
        if not isinstance(depots, dict):
            continue
        plan = _plan_from_depots(dlc_id, depots, language, os_name)
        # Every required depot has a public gid: the plan only takes those.
        own = {d: _public_gid(depots[d]) for d in plan.required - game_depot_ids}
        if own:
            plans[dlc_id] = own
    return plans


def _plan_from_depots(
    appid: int, depots: dict, language: str, os_name: str
) -> DepotPlan:
    """The depots of one app's `depots` section that an (os, language) install gets."""
    required: set[str] = set()
    shared: set[str] = set()
    shared_owner: dict[str, str] = {}
    for depot_id, entry in depots.items():
        if not depot_id.isdigit() or not isinstance(entry, dict):
            continue
        # A shared depot is installed once under its owning app, not here.
        if "depotfromapp" in entry or "sharedinstall" in entry:
            shared.add(depot_id)
            if isinstance(entry.get("depotfromapp"), str):
                shared_owner[depot_id] = entry["depotfromapp"]
            continue
        # Another app's DLC is not part of this install -- but a DLC app's own
        # depots carry its own id as dlcappid, and are exactly what it installs.
        dlc_owner = entry.get("dlcappid")
        if (dlc_owner and dlc_owner != str(appid)) or entry.get("optional") == "1":
            continue
        # A placeholder (BG3 lists 1419654 as `{}`): no manifest on the branch
        # depotdownloader fetches means nothing to download, so never missing.
        if _public_gid(entry) is None:
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
    return DepotPlan(required=required, shared=shared, shared_owner=shared_owner)
