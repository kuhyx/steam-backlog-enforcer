"""Tests for _web_views — the read-only API projections."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _steam_state, _web_views
from steam_backlog_enforcer._backups import StateBackup
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

_PKG = "steam_backlog_enforcer._web_views"


class TestStatus:
    def test_manual_pick_fields(self) -> None:
        full = _web_views._manual_pick(
            {"app_id": 1, "game_name": "One", "age_days": 2.345}
        )
        assert full == {"app_id": 1, "name": "One", "age_days": 2.3}

    def test_unknown_name_and_age(self) -> None:
        bare = _web_views._manual_pick({"app_id": 2, "age_days": None})
        assert bare == {"app_id": 2, "name": "2", "age_days": 0.0}

    def test_status_view_reshapes_the_payload(self) -> None:
        raw = {
            "assigned_game_installed": None,
            "manual_picks": [{"app_id": 3, "game_name": "G", "age_days": 1.0}],
            "other": "kept",
        }
        with patch(f"{_PKG}.status_payload", return_value=raw):
            body = payload_of(_web_views.status_view(make_request()))
        assert body["assigned_game_installed"] is False
        assert body["manual_picks"] == [{"app_id": 3, "name": "G", "age_days": 1.0}]
        assert body["other"] == "kept"


class TestDatasetViews:
    def test_stats_projects_two_keys(self) -> None:
        full = {"default_summary": {"a": 1}, "pace_vs_hltb": [2], "games": []}
        with (
            patch(f"{_PKG}.build_web_dataset"),
            patch(f"{_PKG}.dataset_to_payload", return_value=full),
        ):
            reply = _web_views.stats_view(make_request())
        assert reply.payload == {"default_summary": {"a": 1}, "pace_vs_hltb": [2]}

    def test_dataset_view(self) -> None:
        with (
            patch(f"{_PKG}.build_web_dataset"),
            patch(f"{_PKG}.dataset_to_payload", return_value={"games": []}),
        ):
            assert _web_views.dataset_view(make_request()).payload == {"games": []}

    @pytest.mark.parametrize(("query", "demo"), [({}, False), ({"demo": "1"}, True)])
    def test_budget_view(self, query: dict[str, str], *, demo: bool) -> None:
        with patch(f"{_PKG}.build_budget_snapshot", return_value={"x": 1}) as build:
            reply = _web_views.budget_view(make_request(query=query))
        build.assert_called_once_with(demo=demo)
        assert reply.payload == {"x": 1}


class TestInstalled:
    def test_size_read_from_the_manifest(self) -> None:
        manifest = _steam_state.STEAMAPPS_PATH / "appmanifest_5.acf"
        manifest.write_text('"AppState"\n{\n\t"SizeOnDisk"\t\t"1234"\n}', "utf-8")
        assert _web_views._size_on_disk(5) == 1234

    def test_size_unknown_without_a_match_or_a_file(self) -> None:
        manifest = _steam_state.STEAMAPPS_PATH / "appmanifest_6.acf"
        manifest.write_text('"AppState" {}', encoding="utf-8")
        assert _web_views._size_on_disk(6) == 0
        assert _web_views._size_on_disk(7) == 0

    def test_installed_view(self) -> None:
        with (
            patch(f"{_PKG}.get_installed_games", return_value=[(5, "Five")]),
            patch(f"{_PKG}.allowed_app_ids", return_value={5}),
            patch(f"{_PKG}.is_protected_app", return_value=False),
            patch(f"{_PKG}._size_on_disk", return_value=9),
        ):
            reply = _web_views.installed_view(make_request())
        assert payload_of(reply) == {
            "games": [
                {
                    "app_id": 5,
                    "name": "Five",
                    "size_bytes": 9,
                    "assigned": True,
                    "protected": False,
                }
            ]
        }


class TestSimpleViews:
    def test_commands(self) -> None:
        with patch(f"{_PKG}.command_specs", return_value=[{"name": "scan"}]):
            assert _web_views.commands_view(make_request()).payload == [
                {"name": "scan"}
            ]

    def test_setup_status_never_carries_the_key(self) -> None:
        unset = _web_views.setup_status(Config())
        assert unset == {"configured": False, "has_api_key": False, "steam_id": None}
        done = _web_views.setup_status(Config(steam_api_key="k", steam_id="7"))
        assert done == {"configured": True, "has_api_key": True, "steam_id": "7"}

    def test_setup_view(self) -> None:
        body = payload_of(_web_views.setup_view(make_request()))
        assert body["configured"] is False

    def test_backups(self) -> None:
        backup = StateBackup("id1", "t", "r", 4)
        with patch(f"{_PKG}.list_backups", return_value=[backup]):
            reply = _web_views.backups_view(make_request())
        assert reply.payload == [backup.to_json()]
