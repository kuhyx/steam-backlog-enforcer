import pytest
from _appinfo_blob import encode

from steam_installer import appinfo


def _app_block(monkeypatch, block):
    monkeypatch.setattr(appinfo, "_fetch_app_block", lambda appid: block)


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


def test_get_depot_plan_selects_only_this_language_and_os(monkeypatch):
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})

    plan = appinfo.get_depot_plan(1771300, language="english", os_name="windows")

    assert plan.required == {"1771302", "1771303", "1771306"}
    assert plan.shared == {"228989"}
    assert plan.all_expected == {"1771302", "1771303", "1771306", "228989"}


def test_get_depot_plan_switches_language(monkeypatch):
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})
    plan = appinfo.get_depot_plan(1771300, language="czech")
    assert "1771305" in plan.required
    assert "1771306" not in plan.required


def test_get_depot_plan_excludes_other_os(monkeypatch):
    _app_block(
        monkeypatch,
        {"depots": {"10": {"config": {"oslist": "linux"}, **_PUB}, "11": {"config": {}, **_PUB}}},
    )
    plan = appinfo.get_depot_plan(1771300, os_name="windows")
    assert plan.required == {"11"}


def test_get_depot_plan_skips_optional_depots(monkeypatch):
    _app_block(monkeypatch, {"depots": {"10": {"optional": "1", **_PUB}, "11": _PUB}})
    assert appinfo.get_depot_plan(1771300).required == {"11"}


def test_get_depot_plan_rejects_malformed_depots_section(monkeypatch):
    _app_block(monkeypatch, {"depots": "not-a-dict"})
    with pytest.raises(appinfo.AppInfoError, match="depots"):
        appinfo.get_depot_plan(1771300)


def test_get_depot_plan_with_no_depots_is_empty(monkeypatch):
    """An app with no depot list yields nothing required -- callers must not
    read that as "everything downloaded fine"."""
    _app_block(monkeypatch, {})
    plan = appinfo.get_depot_plan(1771300)
    assert plan.required == set()
    assert plan.shared == set()


def test_get_build_id_reads_public_branch(monkeypatch):
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})
    assert appinfo.get_build_id(1771300) == "23914554"


def test_get_build_id_missing_branch_returns_none(monkeypatch):
    _app_block(monkeypatch, {"depots": {"branches": {}}})
    assert appinfo.get_build_id(1771300) is None


def test_get_build_id_without_depots_returns_none(monkeypatch):
    _app_block(monkeypatch, {})
    assert appinfo.get_build_id(1771300) is None


def test_get_metadata_reads_name_and_installdir(monkeypatch):
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


def test_get_metadata_falls_back_to_config_installdir(monkeypatch):
    _app_block(
        monkeypatch,
        {"common": {"name": "Game"}, "config": {"installdir": "GameDir"}},
    )
    assert appinfo.get_metadata(1).installdir == "GameDir"


def test_get_metadata_requires_name(monkeypatch):
    _app_block(monkeypatch, {"common": {"installdir": "GameDir"}})
    with pytest.raises(appinfo.AppInfoError, match="no name field"):
        appinfo.get_metadata(1)


def test_get_metadata_requires_installdir(monkeypatch):
    _app_block(monkeypatch, {"common": {"name": "Game"}})
    with pytest.raises(appinfo.AppInfoError, match="no installdir"):
        appinfo.get_metadata(1)


def test_get_metadata_rejects_malformed_common_section(monkeypatch):
    _app_block(monkeypatch, {"common": "not-a-dict"})
    with pytest.raises(appinfo.AppInfoError, match="no 'common' section"):
        appinfo.get_metadata(1)


# The block steamcmd's app_info_print used to return for KCD2, now as Steam
# keeps it in its binary cache. The differential tests below pin that the
# cache gives the same answers the steamcmd text did.
KCD2 = {
    "common": {"name": "Kingdom Come: Deliverance II", "installdir": "KingdomComeDeliverance2"},
    "depots": {
        "1771303": {"config": {"oslist": "windows"}},
        "branches": {"public": {"buildid": 23914554}},
    },
}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Point appinfo at a fixture cache; returns a writer for its apps."""
    path = tmp_path / "appinfo.vdf"
    monkeypatch.setattr(appinfo.appinfo_cache, "default_path", lambda: path)

    def write(apps):
        path.write_bytes(encode(apps))

    return write


def test_metadata_comes_from_steams_cache(cache):
    cache({1771300: KCD2})
    metadata = appinfo.get_metadata(1771300)
    assert metadata.name == "Kingdom Come: Deliverance II"
    assert metadata.installdir == "KingdomComeDeliverance2"


def test_get_build_id_through_the_real_parser(cache):
    # Stored as an int32 in the binary cache; still a string like steamcmd's.
    cache({1771300: KCD2})
    assert appinfo.get_build_id(1771300) == "23914554"


def test_app_missing_from_the_cache_fails_with_the_fix(cache):
    cache({1771300: KCD2})
    with pytest.raises(appinfo.AppInfoError, match="start Steam once, let it sync, rerun"):
        appinfo.get_metadata(999999999)


def test_unreadable_cache_fails_with_the_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(
        appinfo.appinfo_cache, "default_path", lambda: tmp_path / "missing.vdf"
    )
    with pytest.raises(appinfo.AppInfoError, match="start Steam once"):
        appinfo.get_metadata(1)


def test_dlc_missing_from_the_cache_counts_as_not_owned(cache):
    """Steam caches app info for what the account owns; on 2026-11-22 only 1828
    of 7102 listed DLC ids were in the cache. Refusing on a missing one would
    block installs that worked with steamcmd."""
    game = {**KCD2, "extended": {"listofdlc": "500,600"}}
    dlc = {"depots": {"501": {"manifests": {"public": {"gid": "9"}}}}}
    cache({1771300: game, 500: dlc})
    assert appinfo.get_dlc_plans(1771300) == {500: {"501": "9"}}


def test_get_build_id_handles_non_dict_sections(monkeypatch):
    for block in (
        {"depots": "scalar"},
        {"depots": {"branches": "scalar"}},
        {"depots": {"branches": {"public": "x"}}},
    ):
        _app_block(monkeypatch, block)
        assert appinfo.get_build_id(1) is None


def test_get_build_id_returns_none_when_buildid_not_a_string(monkeypatch):
    _app_block(monkeypatch, {"depots": {"branches": {"public": {"buildid": {}}}}})
    assert appinfo.get_build_id(1) is None
