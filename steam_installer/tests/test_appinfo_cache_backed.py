"""get_metadata/get_build_id/get_dlc_plans answered from Steam's binary cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from steam_installer import appinfo
from steam_installer.tests._appinfo_blob import encode

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# The block steamcmd's app_info_print used to return for KCD2, now as Steam
# keeps it in its binary cache. The differential tests below pin that the
# cache gives the same answers the steamcmd text did.
KCD2: dict[str, Any] = {
    "common": {
        "name": "Kingdom Come: Deliverance II",
        "installdir": "KingdomComeDeliverance2",
    },
    "depots": {
        "1771303": {"config": {"oslist": "windows"}},
        "branches": {"public": {"buildid": 23914554}},
    },
}


@pytest.fixture(name="cache")
def _cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[int, Any]], None]:
    """Point appinfo at a fixture cache; returns a writer for its apps."""
    path = tmp_path / "appinfo.vdf"
    monkeypatch.setattr(appinfo.appinfo_cache, "default_path", lambda: path)

    def write(apps: dict[int, Any]) -> None:
        path.write_bytes(encode(apps))

    return write


def test_metadata_comes_from_steams_cache(
    cache: Callable[[dict[int, Any]], None],
) -> None:
    """Metadata comes from Steam's cache."""
    cache({1771300: KCD2})
    metadata = appinfo.get_metadata(1771300)
    assert metadata.name == "Kingdom Come: Deliverance II"
    assert metadata.installdir == "KingdomComeDeliverance2"


def test_get_build_id_through_the_real_parser(
    cache: Callable[[dict[int, Any]], None],
) -> None:
    # Stored as an int32 in the binary cache; still a string like steamcmd's.
    """Get build id through the real parser."""
    cache({1771300: KCD2})
    assert appinfo.get_build_id(1771300) == "23914554"


def test_app_missing_from_the_cache_fails_with_the_fix(
    cache: Callable[[dict[int, Any]], None],
) -> None:
    """App missing from the cache fails with the fix."""
    cache({1771300: KCD2})
    with pytest.raises(
        appinfo.AppInfoError, match="start Steam once, let it sync, rerun"
    ):
        appinfo.get_metadata(999999999)


def test_unreadable_cache_fails_with_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unreadable cache fails with the fix."""
    monkeypatch.setattr(
        appinfo.appinfo_cache, "default_path", lambda: tmp_path / "missing.vdf"
    )
    with pytest.raises(appinfo.AppInfoError, match="start Steam once"):
        appinfo.get_metadata(1)


def test_dlc_missing_from_the_cache_counts_as_not_owned(
    cache: Callable[[dict[int, Any]], None],
) -> None:
    """Steam caches app info for what the account owns; on 2026-11-22 only 1828
    of 7102 listed DLC ids were in the cache. Refusing on a missing one would
    block installs that worked with steamcmd."""
    game = {**KCD2, "extended": {"listofdlc": "500,600"}}
    dlc = {"depots": {"501": {"manifests": {"public": {"gid": "9"}}}}}
    cache({1771300: game, 500: dlc})
    assert appinfo.get_dlc_plans(1771300) == {500: {"501": "9"}}
