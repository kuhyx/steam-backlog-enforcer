"""Depot plans against what the public branch actually ships.

Split from test_appinfo.py (250-line cap): these are the depots-without-a-
manifest cases that made a finished BG3 download read as incomplete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_installer import appinfo

if TYPE_CHECKING:
    import pytest


def _app_block(monkeypatch: pytest.MonkeyPatch, block: dict[str, object]) -> None:
    monkeypatch.setattr(appinfo, "fetch_app_block", lambda appid: block)


# Shape taken from a real `app_info_print 1086940` (Baldur's Gate 3, build
# 25605617): depots listed with no manifest for the public branch are
# placeholders. depotdownloader has nothing to fetch for them, so demanding
# them turned a finished 160 GB download into "the download did not finish".
BG3_DEPOTS = {
    "1086941": {
        "config": {"oslist": "windows"},
        "manifests": {"public": {"gid": "8253106406752983615"}},
    },
    "1419654": {},
    "1419655": {"config": {"oslist": "windows"}},
    "1419656": {"manifests": {"release_patch_7_hf3": {"gid": "1"}}},
    "2378500": {
        "dlcappid": "2378500",
        "manifests": {"public": {"gid": "6453229909780803137"}},
    },
}


def test_get_depot_plan_skips_depots_without_a_public_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get depot plan skips depots without a public manifest."""
    _app_block(monkeypatch, {"depots": BG3_DEPOTS})
    assert appinfo.get_depot_plan(1086940).required == {"1086941"}


def test_get_depot_plan_records_every_public_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DLC depots too: the finish check proves the build from these gids."""
    _app_block(monkeypatch, {"depots": BG3_DEPOTS})
    assert appinfo.get_depot_plan(1086940).manifests == {
        "1086941": "8253106406752983615",
        "2378500": "6453229909780803137",
    }
