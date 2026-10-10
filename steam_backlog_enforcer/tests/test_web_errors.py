"""Tests for _web_errors — one code, one HTTP status."""

from __future__ import annotations

from http import HTTPStatus

import pytest

from steam_backlog_enforcer import _web_errors
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer.jobs._errors import JobError


class TestApiError:
    def test_status_comes_from_the_code_table(self) -> None:
        err = _web_errors.ApiError("no", code="locked")
        assert err.status == HTTPStatus.CONFLICT
        assert str(err) == "locked: no"

    def test_unknown_code_is_a_bad_gateway(self) -> None:
        err = _web_errors.ApiError("x", code="mystery")
        assert err.status == HTTPStatus.BAD_GATEWAY

    def test_explicit_status_wins(self) -> None:
        err = _web_errors.ApiError("x", code="locked", status=HTTPStatus.GONE)
        assert err.status == HTTPStatus.GONE

    def test_body_and_headers_without_a_delay(self) -> None:
        err = _web_errors.ApiError("m", code="busy")
        assert err.body() == {"error": "busy", "message": "m"}
        assert err.headers() == {}

    def test_body_and_headers_with_a_delay(self) -> None:
        err = _web_errors.ApiError("m", code="rate_limited", retry_after=0.2)
        assert err.body()["retry_after_seconds"] == 0.2
        assert err.headers() == {"Retry-After": "1"}
        later = _web_errors.ApiError("m", code="rate_limited", retry_after=61.5)
        assert later.headers() == {"Retry-After": "62"}


class TestConverters:
    def test_not_found(self) -> None:
        err = _web_errors.not_found("gone")
        assert (err.code, err.status) == ("not_found", HTTPStatus.NOT_FOUND)

    def test_from_job_error(self) -> None:
        err = _web_errors.from_job_error(JobError("busy now", code="busy"))
        assert (err.code, err.message) == ("busy", "busy now")

    def test_from_ctl_error_keeps_a_known_code_and_delay(self) -> None:
        exc = CtlError("rate_limited", "slow", {"retry_after_seconds": 30})
        err = _web_errors.from_ctl_error(exc)
        assert (err.code, err.retry_after) == ("rate_limited", 30.0)

    def test_from_ctl_error_maps_unknown_codes_to_op_failed(self) -> None:
        err = _web_errors.from_ctl_error(CtlError("weird", ""))
        assert (err.code, err.message, err.retry_after) == ("op_failed", "weird", None)

    @pytest.mark.parametrize("retry", ["soon", None])
    def test_from_ctl_error_ignores_a_non_numeric_delay(self, retry: object) -> None:
        exc = CtlError("busy", "m", {"retry_after_seconds": retry})
        assert _web_errors.from_ctl_error(exc).retry_after is None

    def test_daemon_unreachable(self) -> None:
        err = _web_errors.daemon_unreachable("no socket")
        assert err.code == "daemon_unreachable"
        assert "no socket" in err.message
