"""Structured compat rows: what ``--map-installed --apply`` would do per game."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import anticheat, compat_apply, compat_map, compat_rows
from steam_installer.tests._map_data import NATIVE, PLAIN, TOOL
from steam_installer.tests._steam_root import build_root

if TYPE_CHECKING:
    from pathlib import Path

TOOL_NAME = compat_map.TOOL


@pytest.fixture(name="root")
def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Steam root with games 10 (Plain), 20 (Native), 40 (uncached) and a tool."""
    return build_root(
        tmp_path,
        monkeypatch,
        cached={10: PLAIN, 20: NATIVE, 1493710: TOOL},
        installed=(10, 20, 40, 1493710),
        anticheat_json=b"[]",
    )


def _by_id(root: Path) -> dict[int, compat_rows.Row]:
    return {row.appid: row for row in compat_rows.rows(root)}


def _set_entry(root: Path, name: str, priority: str) -> None:
    config = root / "config" / "config.vdf"
    compat_map.map_app(config, 10)
    text = config.read_text().replace(TOOL_NAME, name)
    config.write_text(text.replace(f'"{compat_map.PRIORITY}"', f'"{priority}"'))


def test_installed_games_only_tools_skipped(root: Path) -> None:
    """Every installed game is a row; Steam's own tools are not."""
    assert sorted(_by_id(root)) == [10, 20, 40]


def test_a_safe_unmapped_game_changes(root: Path) -> None:
    """Plain is Windows-only and unmapped: apply maps it."""
    row = _by_id(root)[10]
    assert (row.name, row.current, row.decided) == ("Plain", None, TOOL_NAME)
    assert (row.map, row.changes, row.reasons, row.note) == (True, True, (), None)


def test_a_native_game_keeps_valves_default(root: Path) -> None:
    """Native keeps Valve's default, with the decision's reason."""
    row = _by_id(root)[20]
    assert (row.decided, row.map, row.changes) == (None, False, False)
    assert row.reasons == ("native",)


def test_an_uncached_game_is_listed_unchanged(root: Path) -> None:
    """An installed game missing from the app cache is a row that never changes."""
    row = _by_id(root)[40]
    assert (row.name, row.cached, row.changes, row.decided) == (
        "Game40",
        False,
        False,
        None,
    )
    assert row.reasons == ("not in Steam's app cache",)


def test_already_mapped_does_not_change(root: Path) -> None:
    """A game already on the native tool is noted and unchanged."""
    compat_map.map_app(root / "config" / "config.vdf", 10)
    row = _by_id(root)[10]
    assert (row.current, row.priority, row.decided) == (TOOL_NAME, "250", TOOL_NAME)
    assert (row.changes, row.note) == (False, "already mapped")


def test_a_user_choice_is_kept(root: Path) -> None:
    """A tool kuhy chose (non-Valve priority) is kept, exactly as map_app keeps it."""
    _set_entry(root, "GE-Proton10", "250")
    row = _by_id(root)[10]
    assert (row.current, row.decided, row.changes) == (
        "GE-Proton10",
        "GE-Proton10",
        False,
    )
    assert row.note == "kept: already mapped to GE-Proton10 (priority 250)"


def test_valves_own_choice_is_replaced(root: Path) -> None:
    """An entry at Valve's priority is Valve's choice: apply replaces it."""
    _set_entry(root, "proton_9", compat_map.VALVE_PRIORITY)
    row = _by_id(root)[10]
    assert (row.current, row.decided, row.changes) == ("proton_9", TOOL_NAME, True)


def test_explicit_appids_include_tools_and_uncached(root: Path) -> None:
    """``appids`` decides exactly those ids, tools included, in the given order."""
    got = compat_rows.rows(root, appids=[1493710, 999])
    assert [(r.appid, r.cached) for r in got] == [(1493710, True), (999, False)]
    assert got[1].name == ""


def test_to_json_shape(root: Path) -> None:
    """The web contract's CompatRow keys, reasons as a list."""
    assert _by_id(root)[20].to_json() == {
        "app_id": 20,
        "name": "Native",
        "current": None,
        "priority": None,
        "decided": None,
        "reasons": ["native"],
        "note": None,
        "map": False,
        "changes": False,
        "cached": True,
    }


@pytest.mark.parametrize(
    ("entry", "action"),
    [
        (None, None),
        (("", ""), None),
        ((TOOL_NAME, "250"), "already"),
        (("GE-Proton10", "250"), "kept"),
        (("proton_9", compat_map.VALVE_PRIORITY), None),
    ],
)
def test_keep_reason(entry: tuple[str, str] | None, action: str | None) -> None:
    """The one predicate map_app and the rows share."""
    held = compat_map.keep_reason(entry)
    assert (held.action if held else None) == action


def _cache(tmp_path: Path, age: float) -> Path:
    cache = tmp_path / "ac.json"
    cache.write_text('[{"storeIds": {"steam": "7"}}]')
    stamp = time.time() - age
    os.utime(cache, (stamp, stamp))
    return cache


def test_steam_ids_max_age_reads_a_fresh_cache_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache younger than ``max_age`` is used without touching the network."""

    def boom() -> Never:
        pytest.fail("downloaded")

    monkeypatch.setattr(anticheat, "_download", boom)
    assert anticheat.steam_ids(_cache(tmp_path, 10), max_age=60) == {7}


def test_steam_ids_max_age_downloads_a_stale_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older (or missing) cache is downloaded as before."""
    monkeypatch.setattr(
        anticheat, "_download", lambda: b'[{"storeIds": {"steam": "8"}}]'
    )
    assert anticheat.steam_ids(_cache(tmp_path, 120), max_age=60) == {8}
    assert anticheat.steam_ids(tmp_path / "none.json", max_age=60) == {8}


def test_context_passes_max_age(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``Context(anticheat_max_age=...)`` reaches ``steam_ids``."""
    seen: list[float | None] = []

    def ids(max_age: float | None = None) -> set[int]:
        seen.append(max_age)
        return set()

    monkeypatch.setattr(anticheat, "steam_ids", ids)
    compat_apply.Context(root, anticheat_max_age=5.0)
    compat_apply.Context(root)
    assert seen == [5.0, None]
