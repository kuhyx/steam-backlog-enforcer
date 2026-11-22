"""Which games get the native Proton, and why the others keep Valve's default."""

import json

import pytest

from steam_installer import anticheat, compat_decide

WINDOWS_ONLY = {
    "common": {"oslist": "windows"},
    "depots": {"11": {"config": {"oslist": "windows"}}, "12": {}},
    "config": {"launch": {"0": {"config": {"oslist": "windows"}}}},
}


def _decide(block=WINDOWS_ONLY, **kw):
    args = {"anticheat": set(), "overrides": {}, "owned_dlc": False, "tool_ready": True}
    args.update(kw)
    return compat_decide.decide(10, block, **args)


def test_a_plain_windows_game_is_mapped():
    decision = _decide()
    assert decision.map
    assert decision.describe() == "map"


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        ({**WINDOWS_ONLY, "common": {"oslist": "windows,linux"}}, "native"),
        ({**WINDOWS_ONLY, "depots": {"11": {"config": {"oslist": "linux"}}}}, "native"),
        (
            {**WINDOWS_ONLY, "config": {"launch": {"0": {"config": {"oslist": "linux"}}}}},
            "native",
        ),
        ({**WINDOWS_ONLY, "common": {"oslist": "windows,macos"}}, "not Windows-only"),
        ({**WINDOWS_ONLY, "common": {}}, "no OS list"),
        ({"common": "x"}, "no OS list"),
        ({**WINDOWS_ONLY, "depots": {"11": {"depotfromapp": "228980"}}}, "shared depots"),
        ({**WINDOWS_ONLY, "depots": {"11": {"sharedinstall": "1"}}}, "shared depots"),
    ],
)
def test_unsafe_games_keep_valves_default(block, reason):
    decision = _decide(block)
    assert not decision.map
    assert reason in decision.reasons


def test_odd_shapes_are_ignored_not_crashed_on():
    block = {
        "common": {"oslist": "windows"},
        "depots": {"branches": {"public": {}}, "11": "scalar", "12": {"config": "x"}},
        "config": {"launch": "scalar"},
    }
    assert _decide(block).map
    assert _decide({**block, "config": {"launch": {"0": "x", "1": {"config": "y"}}}}).map
    assert _decide({**block, "depots": "scalar", "config": "scalar"}).map


def test_anti_cheat_whatever_its_status():
    assert _decide(anticheat={10}).reasons == ["anti-cheat"]


def test_no_anti_cheat_list_means_no_mapping():
    assert _decide(anticheat=None).reasons == ["anti-cheat list unavailable"]


def test_owned_dlc_is_left_on_valves_default_until_tested_live():
    assert _decide(owned_dlc=True).reasons == ["owned DLC"]


def test_override_and_missing_tool():
    assert _decide(overrides={"10": "crashes at intro"}).reasons == [
        "override: crashes at intro"
    ]
    assert _decide(tool_ready=False).reasons == ["native Proton not installed"]


def test_every_reason_is_reported():
    block = {**WINDOWS_ONLY, "common": {"oslist": "windows,linux"}}
    decision = _decide(block, anticheat={10})
    assert decision.describe() == "Valve default: anti-cheat, native"


def test_overrides_file_is_tracked_and_valid():
    assert compat_decide.load_overrides() == {}


def test_overrides_file_must_map_ids_to_reasons(tmp_path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"10": "why"}))
    assert compat_decide.load_overrides(path) == {"10": "why"}
    for bad in ([1], {"x": "why"}, {"10": 3}):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="compat_overrides"):
            compat_decide.load_overrides(path)


def test_tool_ready_needs_the_manifest_and_the_pinned_stamp(tmp_path):
    tool = tmp_path / "proton-cachyos-native"
    assert not compat_decide.tool_ready(tool, "1:2-3")
    tool.mkdir()
    (tool / "toolmanifest.vdf").write_text("x")
    assert not compat_decide.tool_ready(tool, "1:2-3")
    (tool / "VERSION").write_text("1:2-2\n")
    assert not compat_decide.tool_ready(tool, "1:2-3")
    (tool / "VERSION").write_text("1:2-3\n")
    assert compat_decide.tool_ready(tool, "1:2-3")


GAMES = [
    {"name": "CS", "storeIds": {"steam": "730"}, "status": "Supported"},
    {"name": "Epic only", "storeIds": {"epic": "x"}},
    {"name": "Broken", "storeIds": "x"},
    "not a game",
]


def test_anticheat_list_is_fetched_and_cached(tmp_path, monkeypatch):
    cache = tmp_path / "ac.json"
    monkeypatch.setattr(anticheat, "_download", lambda: json.dumps(GAMES).encode())
    assert anticheat.steam_ids(cache) == {730}
    assert json.loads(cache.read_text()) == GAMES


def test_anticheat_falls_back_to_the_last_good_copy(tmp_path, monkeypatch):
    cache = tmp_path / "ac.json"
    cache.write_text(json.dumps(GAMES))

    def offline():
        raise OSError("no network")

    monkeypatch.setattr(anticheat, "_download", offline)
    assert anticheat.steam_ids(cache) == {730}


def test_anticheat_with_no_fetch_and_no_cache_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(anticheat, "_download", lambda: b"{not json")
    assert anticheat.steam_ids(tmp_path / "ac.json") is None
    (tmp_path / "ac.json").write_text('{"a": 1}')
    assert anticheat.steam_ids(tmp_path / "ac.json") is None


def test_anticheat_download_reads_the_upstream_url(monkeypatch):
    seen = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(url, timeout):
        seen["url"] = url
        return _Response()

    monkeypatch.setattr(anticheat.urllib.request, "urlopen", fake_urlopen)
    assert anticheat._download() == b"[]"
    assert "AreWeAntiCheatYet" in seen["url"]
