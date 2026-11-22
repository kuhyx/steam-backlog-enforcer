"""Tests for appinfo."""

from __future__ import annotations

import pytest

from steam_installer import appinfo


def _app_block(monkeypatch: pytest.MonkeyPatch, block: dict[str, object]) -> None:
    monkeypatch.setattr(appinfo, "fetch_app_block", lambda appid: block)


# Every real depot that has content ships a manifest on the public branch.
_PUB = {"manifests": {"public": {"gid": "1"}}}

# Shape taken from a real `app_info_print 1771300`: 12 depots, of which an
# english/windows install only ever fetches three.
KCD2_DEPOTS = {
    "228989": {"depotfromapp": "228980", "config": {"oslist": "windows"}, **_PUB},
    "1771302": {"config": {"oslist": "windows"}, **_PUB},
    "1771303": {"config": {"oslist": "windows"}, **_PUB},
    "1771304": {"dlcappid": "3406020", "config": {"oslist": "windows"}, **_PUB},
    "1771305": {"config": {"oslist": "windows", "language": "czech"}, **_PUB},
    "1771306": {"config": {"oslist": "windows", "language": "english"}, **_PUB},
    "1771307": {"config": {"oslist": "windows", "language": "french"}, **_PUB},
    "4075290": {"dlcappid": "4075290", **_PUB},
    "branches": {"public": {"buildid": "23914554"}},
}


def test_get_depot_plan_selects_only_this_language_and_os(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get depot plan selects only this language and os."""
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})

    plan = appinfo.get_depot_plan(1771300, language="english", os_name="windows")

    assert plan.required == {"1771302", "1771303", "1771306"}
    assert plan.shared == {"228989"}
    assert plan.all_expected == {"1771302", "1771303", "1771306", "228989"}


def test_get_depot_plan_switches_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get depot plan switches language."""
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})
    plan = appinfo.get_depot_plan(1771300, language="czech")
    assert "1771305" in plan.required
    assert "1771306" not in plan.required


def test_get_depot_plan_excludes_other_os(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get depot plan excludes other os."""
    _app_block(
        monkeypatch,
        {
            "depots": {
                "10": {"config": {"oslist": "linux"}, **_PUB},
                "11": {"config": {}, **_PUB},
            }
        },
    )
    plan = appinfo.get_depot_plan(1771300, os_name="windows")
    assert plan.required == {"11"}


def test_get_depot_plan_skips_optional_depots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get depot plan skips optional depots."""
    _app_block(monkeypatch, {"depots": {"10": {"optional": "1", **_PUB}, "11": _PUB}})
    assert appinfo.get_depot_plan(1771300).required == {"11"}


def test_get_depot_plan_rejects_malformed_depots_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get depot plan rejects malformed depots section."""
    _app_block(monkeypatch, {"depots": "not-a-dict"})
    with pytest.raises(appinfo.AppInfoError, match="depots"):
        appinfo.get_depot_plan(1771300)


def test_get_depot_plan_with_no_depots_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An app with no depot list yields nothing required -- callers must not
    read that as "everything downloaded fine"."""
    _app_block(monkeypatch, {})
    plan = appinfo.get_depot_plan(1771300)
    assert plan.required == set()
    assert plan.shared == set()


def test_get_build_id_reads_public_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get build id reads public branch."""
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})
    assert appinfo.get_build_id(1771300) == "23914554"


def test_get_build_id_missing_branch_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get build id missing branch returns none."""
    _app_block(monkeypatch, {"depots": {"branches": {}}})
    assert appinfo.get_build_id(1771300) is None


def test_get_build_id_without_depots_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get build id without depots returns none."""
    _app_block(monkeypatch, {})
    assert appinfo.get_build_id(1771300) is None


def test_get_metadata_reads_name_and_installdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get metadata reads name and installdir."""
    _app_block(
        monkeypatch,
        {
            "common": {
                "name": "Kingdom Come: Deliverance II",
                "installdir": "KingdomComeDeliverance2",
            }
        },
    )
    metadata = appinfo.get_metadata(1771300)
    assert metadata.name == "Kingdom Come: Deliverance II"
    assert metadata.installdir == "KingdomComeDeliverance2"


def test_get_metadata_falls_back_to_config_installdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get metadata falls back to config installdir."""
    _app_block(
        monkeypatch,
        {"common": {"name": "Game"}, "config": {"installdir": "GameDir"}},
    )
    assert appinfo.get_metadata(1).installdir == "GameDir"


def test_get_metadata_requires_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get metadata requires name."""
    _app_block(monkeypatch, {"common": {"installdir": "GameDir"}})
    with pytest.raises(appinfo.AppInfoError, match="no name field"):
        appinfo.get_metadata(1)


def test_get_metadata_requires_installdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Get metadata requires installdir."""
    _app_block(monkeypatch, {"common": {"name": "Game"}})
    with pytest.raises(appinfo.AppInfoError, match="no installdir"):
        appinfo.get_metadata(1)


def test_get_metadata_rejects_malformed_common_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get metadata rejects malformed common section."""
    _app_block(monkeypatch, {"common": "not-a-dict"})
    with pytest.raises(appinfo.AppInfoError, match="no 'common' section"):
        appinfo.get_metadata(1)


def test_get_build_id_handles_non_dict_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get build id handles non dict sections."""
    for block in (
        {"depots": "scalar"},
        {"depots": {"branches": "scalar"}},
        {"depots": {"branches": {"public": "x"}}},
    ):
        _app_block(monkeypatch, block)
        assert appinfo.get_build_id(1) is None


def test_get_build_id_returns_none_when_buildid_not_a_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get build id returns none when buildid not a string."""
    _app_block(monkeypatch, {"depots": {"branches": {"public": {"buildid": {}}}}})
    assert appinfo.get_build_id(1) is None


def test_a_shared_install_without_an_owner_is_still_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared install without an owner is still shared."""
    _app_block(
        monkeypatch,
        {"depots": {"5": {"sharedinstall": "1"}, "6": {"depotfromapp": "228980"}}},
    )
    plan = appinfo.get_depot_plan(1)
    assert plan.shared == {"5", "6"}
    assert plan.shared_owner == {"6": "228980"}
