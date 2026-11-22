"""Which games get the native Proton, and why the others keep Valve's default."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Never, Self

import pytest

from steam_installer import _http, anticheat, compat_decide
from steam_installer.anticheat import _download as _download_anticheat

if TYPE_CHECKING:
    from pathlib import Path
    import urllib.request

WINDOWS_ONLY = {
    "common": {"oslist": "windows"},
    "depots": {"11": {"config": {"oslist": "windows"}}, "12": {}},
    "config": {"launch": {"0": {"config": {"oslist": "windows"}}}},
}


def _decide(
    block: dict[str, object] | None = None,
    *,
    owned_dlc: bool = False,
    **facts: object,
) -> compat_decide.Decision:
    block = WINDOWS_ONLY if block is None else block
    base = {"anticheat": set(), "overrides": {}, "tool_ready": True}
    shared = compat_decide.Facts(**{**base, **facts})
    return compat_decide.decide(10, block, shared, owned_dlc=owned_dlc)


def test_a_plain_windows_game_is_mapped() -> None:
    """A plain windows game is mapped."""
    decision = _decide()
    assert decision.map
    assert decision.describe() == "map"


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        ({**WINDOWS_ONLY, "common": {"oslist": "windows,linux"}}, "native"),
        ({**WINDOWS_ONLY, "depots": {"11": {"config": {"oslist": "linux"}}}}, "native"),
        (
            {
                **WINDOWS_ONLY,
                "config": {"launch": {"0": {"config": {"oslist": "linux"}}}},
            },
            "native",
        ),
        ({**WINDOWS_ONLY, "common": {"oslist": "windows,macos"}}, "not Windows-only"),
        ({**WINDOWS_ONLY, "common": {}}, "no OS list"),
        ({"common": "x"}, "no OS list"),
        (
            {**WINDOWS_ONLY, "depots": {"11": {"depotfromapp": "228980"}}},
            "shared depots",
        ),
        ({**WINDOWS_ONLY, "depots": {"11": {"sharedinstall": "1"}}}, "shared depots"),
    ],
)
def test_unsafe_games_keep_valves_default(
    block: dict[str, object], reason: str
) -> None:
    """Unsafe games keep valves default."""
    decision = _decide(block)
    assert not decision.map
    assert reason in decision.reasons


def test_odd_shapes_are_ignored_not_crashed_on() -> None:
    """Odd shapes are ignored not crashed on."""
    block = {
        "common": {"oslist": "windows"},
        "depots": {"branches": {"public": {}}, "11": "scalar", "12": {"config": "x"}},
        "config": {"launch": "scalar"},
    }
    assert _decide(block).map
    assert _decide(
        {**block, "config": {"launch": {"0": "x", "1": {"config": "y"}}}}
    ).map
    assert _decide({**block, "depots": "scalar", "config": "scalar"}).map


def test_anti_cheat_whatever_its_status() -> None:
    """Anti cheat whatever its status."""
    assert _decide(anticheat={10}).reasons == ["anti-cheat"]


def test_no_anti_cheat_list_means_no_mapping() -> None:
    """No anti cheat list means no mapping."""
    assert _decide(anticheat=None).reasons == ["anti-cheat list unavailable"]


def test_owned_dlc_is_left_on_valves_default_until_tested_live() -> None:
    """Owned dlc is left on valves default until tested live."""
    assert _decide(owned_dlc=True).reasons == ["owned DLC"]


def test_override_and_missing_tool() -> None:
    """Override and missing tool."""
    assert _decide(overrides={"10": "crashes at intro"}).reasons == [
        "override: crashes at intro"
    ]
    assert _decide(tool_ready=False).reasons == ["native Proton not installed"]


def test_every_reason_is_reported() -> None:
    """Every reason is reported."""
    block = {**WINDOWS_ONLY, "common": {"oslist": "windows,linux"}}
    decision = _decide(block, anticheat={10})
    assert decision.describe() == "Valve default: anti-cheat, native"


def test_overrides_file_is_tracked_and_valid() -> None:
    """Overrides file is tracked and valid."""
    assert compat_decide.load_overrides() == {}


def test_overrides_file_must_map_ids_to_reasons(tmp_path: Path) -> None:
    """Overrides file must map ids to reasons."""
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"10": "why"}))
    assert compat_decide.load_overrides(path) == {"10": "why"}
    for bad in ([1], {"x": "why"}, {"10": 3}):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="compat_overrides"):
            compat_decide.load_overrides(path)


def test_tool_ready_needs_the_manifest_and_the_pinned_stamp(tmp_path: Path) -> None:
    """Tool ready needs the manifest and the pinned stamp."""
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


def test_anticheat_list_is_fetched_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anticheat list is fetched and cached."""
    cache = tmp_path / "ac.json"
    monkeypatch.setattr(anticheat, "_download", lambda: json.dumps(GAMES).encode())
    assert anticheat.steam_ids(cache) == {730}
    assert json.loads(cache.read_text()) == GAMES


def test_anticheat_falls_back_to_the_last_good_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anticheat falls back to the last good copy."""
    cache = tmp_path / "ac.json"
    cache.write_text(json.dumps(GAMES))

    def offline() -> Never:
        msg = "no network"
        raise OSError(msg)

    monkeypatch.setattr(anticheat, "_download", offline)
    assert anticheat.steam_ids(cache) == {730}


def test_anticheat_with_no_fetch_and_no_cache_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anticheat with no fetch and no cache is unknown."""
    monkeypatch.setattr(anticheat, "_download", lambda: b"{not json")
    assert anticheat.steam_ids(tmp_path / "ac.json") is None
    (tmp_path / "ac.json").write_text('{"a": 1}')
    assert anticheat.steam_ids(tmp_path / "ac.json") is None


def test_anticheat_download_reads_the_upstream_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anticheat download reads the upstream url."""
    seen = {}

    class _Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def read(self) -> bytes:
            """The body the fake mirror serves."""
            return b"[]"

    def fake_urlopen(request: urllib.request.Request, **_kw: float) -> _Response:
        seen["url"] = request.full_url
        seen["agent"] = request.get_header("User-agent")
        return _Response()

    monkeypatch.setattr(_http.urllib.request, "urlopen", fake_urlopen)
    assert _download_anticheat() == b"[]"
    assert "AreWeAntiCheatYet" in seen["url"]
    assert seen["agent"] is None  # urllib sends its own default agent
