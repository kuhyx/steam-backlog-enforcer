"""A fake Steam root for the map-installed tests: config, app cache, manifests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from steam_installer import anticheat, compat_apply, vdf
from steam_installer.tests._acf_helpers import stamp_native_tool
from steam_installer.tests._appinfo_blob import encode
from steam_installer.tests._map_data import CONFIG, LOCKED

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    import pytest


def build_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cached: dict[int, dict[str, Any]],
    installed: Iterable[int],
    anticheat_json: bytes,
) -> Path:
    """A Steam root with the stamped tool, an app cache and installed manifests.

    *cached* is the app cache's content; *installed* the appids that get an
    ``appmanifest`` (named ``Game<appid>``), cached or not.
    """
    root = tmp_path / "Steam"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.vdf").write_text(CONFIG)
    stamp_native_tool(root, LOCKED)
    cache = tmp_path / "appinfo.vdf"
    cache.write_bytes(encode(cached))
    monkeypatch.setattr(
        compat_apply.appinfo.appinfo_cache, "default_path", lambda: cache
    )
    monkeypatch.setattr(anticheat, "_download", lambda: anticheat_json)
    steamapps = root / "steamapps"
    steamapps.mkdir()
    for appid in installed:
        state = {"appid": str(appid), "name": f"Game{appid}", "InstalledDepots": {}}
        (steamapps / f"appmanifest_{appid}.acf").write_text(
            vdf.dumps("AppState", state)
        )
    return root
