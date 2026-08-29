"""Tests for _attribution_labels — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _attribution_labels as labels_mod
from steam_backlog_enforcer import _steam_state
from steam_backlog_enforcer._attribution_labels import label_for, labels_for
from steam_backlog_enforcer._counted_procs import CountedProcess


def _manifest(app_id: int, name: str) -> None:
    _steam_state.STEAMAPPS_PATH.mkdir(parents=True, exist_ok=True)
    (_steam_state.STEAMAPPS_PATH / f"appmanifest_{app_id}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{app_id}"\n\t"name"\t\t"{name}"\n}}\n',
        encoding="utf-8",
    )


class TestLabelFor:
    """Resolving each key shape."""

    def setup_method(self) -> None:
        labels_mod._app_names.clear()

    def test_reads_a_steam_name_from_the_appmanifest(self) -> None:
        # A running game is by definition installed, so its manifest exists —
        # which is why this never has to load the 11 MB snapshot.
        _manifest(475150, "Titan Quest Anniversary Edition")
        assert label_for("app:475150") == "Titan Quest Anniversary Edition"

    def test_memoises_the_manifest_read(self) -> None:
        _manifest(440, "Team Fortress 2")
        assert label_for("app:440") == "Team Fortress 2"
        with patch.object(_steam_state, "STEAMAPPS_PATH", None):
            # A second lookup must not touch the filesystem at all.
            assert label_for("app:440") == "Team Fortress 2"

    def test_a_missing_manifest_falls_back_to_the_key(self) -> None:
        assert label_for("app:999999") == "app:999999"

    def test_a_manifest_without_a_name_falls_back_to_the_key(self) -> None:
        _steam_state.STEAMAPPS_PATH.mkdir(parents=True, exist_ok=True)
        (_steam_state.STEAMAPPS_PATH / "appmanifest_5.acf").write_text(
            '"AppState"\n{\n\t"appid"\t\t"5"\n}\n', encoding="utf-8"
        )
        assert label_for("app:5") == "app:5"

    def test_a_non_numeric_app_key_falls_back(self) -> None:
        assert label_for("app:nope") == "app:nope"

    def test_a_counted_process_uses_its_configured_label(self) -> None:
        with patch.object(
            labels_mod,
            "load_counted_processes",
            return_value=(
                CountedProcess(id="osu-lazer", label="osu!lazer", names=frozenset()),
            ),
        ):
            assert label_for("proc:osu-lazer") == "osu!lazer"

    def test_an_unknown_counted_process_falls_back(self) -> None:
        with patch.object(labels_mod, "load_counted_processes", return_value=()):
            assert label_for("proc:gone") == "proc:gone"

    def test_a_launcher_uses_its_process_name(self) -> None:
        assert label_for("launcher:lutris") == "lutris"

    def test_an_unrecognised_key_is_returned_as_is(self) -> None:
        assert label_for("weird") == "weird"


class TestLabelsFor:
    def test_resolves_every_key(self) -> None:
        assert labels_for(["launcher:heroic", "launcher:itch"]) == {
            "launcher:heroic": "heroic",
            "launcher:itch": "itch",
        }
