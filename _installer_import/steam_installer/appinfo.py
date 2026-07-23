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


def _fetch_app_block(appid: int) -> dict:
    result = subprocess.run(
        ["steamcmd", "+login", "anonymous", "+app_info_print", str(appid), "+quit"],
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
