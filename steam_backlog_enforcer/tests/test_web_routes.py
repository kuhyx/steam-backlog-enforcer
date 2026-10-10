"""Tests for _web_routes — the route table and its resolver."""

from __future__ import annotations

import pytest

from steam_backlog_enforcer import _web_jobs, _web_routes, _web_views


class TestResolve:
    def test_static_route(self) -> None:
        assert _web_routes.resolve("GET", "/api/budget") == (
            _web_views.budget_view,
            (),
        )

    def test_captures_the_path_id(self) -> None:
        found = _web_routes.resolve("POST", "/api/jobs/j-1_A/cancel")
        assert found == (_web_jobs.cancel_view, ("j-1_A",))

    def test_same_path_resolves_per_method(self) -> None:
        assert _web_routes.resolve("GET", "/api/jobs") == (_web_jobs.jobs_view, ())
        assert _web_routes.resolve("POST", "/api/jobs") == (
            _web_jobs.create_job_view,
            (),
        )

    def test_known_path_under_another_method(self) -> None:
        assert _web_routes.resolve("DELETE", "/api/budget") == "method"

    @pytest.mark.parametrize("path", ["/api/nope", "/api/jobs/a b", "/api/jobs/"])
    def test_unknown_path(self, path: str) -> None:
        assert _web_routes.resolve("GET", path) is None


class TestEventsPath:
    def test_matches_only_the_stream(self) -> None:
        match = _web_routes.EVENTS_PATH.fullmatch("/api/jobs/abc/events")
        assert match is not None
        assert match.groups() == ("abc",)
        assert _web_routes.EVENTS_PATH.fullmatch("/api/jobs/abc") is None
