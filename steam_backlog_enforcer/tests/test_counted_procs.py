"""Tests for _counted_procs — 100% branch coverage.

The validation here is load-bearing rather than cosmetic: these names are fed
to the budget cutoff and the total-block killer, and `_playtime_kill` signals a
matched PID *and its descendants*. A name like `sh` would take the whole
session down with it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from steam_backlog_enforcer import config as config_mod
from steam_backlog_enforcer._counted_procs import (
    DEFAULT_COUNTED_PROCESSES,
    CountedProcess,
    counted_process_names,
    key_by_name,
    kill_target_names,
    labels_by_key,
    load_counted_processes,
    parse_counted_processes,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(payload: object) -> None:
    config_mod.CONFIG_FILE.write_text(json.dumps(payload), encoding="utf-8")


class TestParse:
    """Turning raw JSON into validated entries."""

    def test_reads_a_well_formed_entry(self) -> None:
        entries = parse_counted_processes(
            [{"id": "osu-lazer", "label": "osu!lazer", "names": ["osu!", "osu-lazer"]}]
        )
        assert entries == (
            CountedProcess(
                id="osu-lazer",
                label="osu!lazer",
                names=frozenset({"osu!", "osu-lazer"}),
            ),
        )

    def test_label_defaults_to_the_id(self) -> None:
        entries = parse_counted_processes([{"id": "quake", "names": ["quake"]}])
        assert entries[0].label == "quake"

    def test_rejects_a_non_list(self) -> None:
        assert parse_counted_processes({"id": "x"}) == ()

    def test_drops_a_non_object_entry(self) -> None:
        assert parse_counted_processes(["nope"]) == ()

    def test_drops_an_entry_with_no_id(self) -> None:
        assert parse_counted_processes([{"names": ["x"]}]) == ()

    def test_drops_an_entry_with_no_usable_names(self) -> None:
        assert parse_counted_processes([{"id": "x", "names": []}]) == ()

    def test_drops_an_entry_whose_names_are_not_a_list(self) -> None:
        assert parse_counted_processes([{"id": "x", "names": "osu!"}]) == ()

    def test_drops_a_duplicate_id(self) -> None:
        entries = parse_counted_processes(
            [
                {"id": "x", "names": ["a"]},
                {"id": "x", "names": ["b"]},
            ]
        )
        assert len(entries) == 1
        assert entries[0].names == frozenset({"a"})

    def test_ignores_non_string_and_blank_names(self) -> None:
        entries = parse_counted_processes([{"id": "x", "names": ["a", 7, "  ", None]}])
        assert entries[0].names == frozenset({"a"})

    def test_refuses_a_shell_or_interpreter_name(self) -> None:
        """`sh` would SIGTERM every shell on the system, and its children."""
        entries = parse_counted_processes(
            [{"id": "osu", "names": ["sh", "dotnet", "osu!"]}]
        )
        assert entries[0].names == frozenset({"osu!"})

    def test_an_entry_of_only_forbidden_names_is_dropped(self) -> None:
        assert parse_counted_processes([{"id": "osu", "names": ["sh"]}]) == ()


class TestLoad:
    """Reading straight from config.json, with no Config to consult."""

    def test_missing_file_falls_back_to_defaults(self) -> None:
        assert load_counted_processes() == DEFAULT_COUNTED_PROCESSES

    def test_unreadable_file_falls_back_to_defaults(self) -> None:
        config_mod.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        assert load_counted_processes() == DEFAULT_COUNTED_PROCESSES

    def test_non_object_payload_falls_back_to_defaults(self) -> None:
        _write([1, 2, 3])
        assert load_counted_processes() == DEFAULT_COUNTED_PROCESSES

    def test_absent_key_falls_back_to_defaults(self) -> None:
        _write({"steam_id": "1"})
        assert load_counted_processes() == DEFAULT_COUNTED_PROCESSES

    def test_an_explicit_empty_list_means_none(self) -> None:
        """Distinct from absent: the user can switch the feature off."""
        _write({"counted_processes": []})
        assert load_counted_processes() == ()

    def test_reads_a_configured_list(self) -> None:
        _write({"counted_processes": [{"id": "q", "names": ["quake"]}]})
        assert load_counted_processes()[0].id == "q"

    def test_the_default_covers_every_osu_layer(self) -> None:
        """The sh wrapper, the AppImage and the game each exec a new comm."""
        assert counted_process_names(DEFAULT_COUNTED_PROCESSES) == frozenset(
            {"osu-lazer", "osu.AppImage", "osu!"}
        )


class TestDerivedViews:
    """The three projections the billing and kill paths consume."""

    _ENTRIES = (
        CountedProcess(id="osu-lazer", label="osu!lazer", names=frozenset({"osu!"})),
    )

    def test_names_of_no_entries_is_empty(self) -> None:
        assert counted_process_names(()) == frozenset()

    def test_key_by_name(self) -> None:
        assert key_by_name(self._ENTRIES) == {"osu!": "proc:osu-lazer"}

    def test_labels_by_key(self) -> None:
        assert labels_by_key(self._ENTRIES) == {"proc:osu-lazer": "osu!lazer"}

    def test_kill_targets_come_from_the_config(self, tmp_path: Path) -> None:
        assert tmp_path.exists()
        _write({"counted_processes": [{"id": "q", "names": ["quake"]}]})
        assert kill_target_names() == frozenset({"quake"})
