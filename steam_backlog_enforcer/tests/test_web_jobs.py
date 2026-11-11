"""Tests for _web_jobs — job routes and backup restore."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _web_jobs
from steam_backlog_enforcer._backups import StateBackup
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_io import Reply
from steam_backlog_enforcer._web_jobs import _enforce_params, _job_request
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

_PKG = "steam_backlog_enforcer._web_jobs"
_BACKUP = StateBackup("20260101T000000Z-abcdef", "t", "r", 1)


def _create(body: dict[str, Any]) -> Reply:
    return _web_jobs.create_job_view(make_request(body=body))


class TestEnforceParams:
    """Translating enforce params from the web form to job params."""

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"demo": 1}, {"demo": 1}),
            ({"mode": "demo"}, {"demo": 1}),
            ({"mode": "restart"}, {"demo": 0}),
        ],
    )
    def test_translation(self, params: dict[str, Any], expected: object) -> None:
        """Each accepted demo/mode spelling maps to the demo flag."""
        assert _enforce_params(params) == expected

    @pytest.mark.parametrize("params", [{}, {"mode": "x"}, {"mode": "demo", "z": 1}])
    def test_bad_mode(self, params: dict[str, Any]) -> None:
        """Missing, unknown or extra params are refused as invalid_params."""
        with pytest.raises(ApiError) as err:
            _enforce_params(params)
        assert err.value.code == "invalid_params"


class TestJobRequest:
    """Parsing the create-job request body."""

    def test_defaults_to_empty_params(self) -> None:
        """A body with only a command yields empty params and no phrase."""
        got = _job_request(make_request(body={"command": "scan"}))
        assert got == ("scan", {}, None)

    def test_enforce_params_are_translated(self) -> None:
        """Enforce params are translated while parsing the body."""
        body = {"command": "enforce", "params": {"mode": "demo"}}
        assert _job_request(make_request(body=body))[1] == {"demo": 1}

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"command": 3},
            {"command": "scan", "params": []},
            {"command": "scan", "confirm_phrase": 3},
        ],
    )
    def test_malformed(self, body: dict[str, Any]) -> None:
        """Bodies with a bad command, params or phrase type are invalid_params."""
        with pytest.raises(ApiError) as err:
            _job_request(make_request(body=body))
        assert err.value.code == "invalid_params"


class TestReadRoutes:
    """The read-only job listing and detail routes."""

    def test_jobs_view(self) -> None:
        """The jobs view returns the job list as its payload."""
        with patch(f"{_PKG}.list_jobs", return_value=[{"id": "a"}]):
            assert _web_jobs.jobs_view(make_request()).payload == [{"id": "a"}]

    def test_job_view(self) -> None:
        """The job view returns the job read for the path id."""
        with patch(f"{_PKG}.read_job", return_value={"id": "a"}) as read:
            assert _web_jobs.job_view(make_request("a")).payload == {"id": "a"}
        read.assert_called_once_with("a")

    def test_unknown_job(self) -> None:
        """An unknown job id is not_found."""
        with pytest.raises(ApiError) as err:
            _web_jobs.job_view(make_request("nope"))
        assert err.value.code == "not_found"


class TestCreateJob:
    """Creating jobs through the web route."""

    def test_unknown_command(self) -> None:
        """A command that is not registered is unknown_command."""
        with pytest.raises(ApiError) as err:
            _create({"command": "rm-rf"})
        assert err.value.code == "unknown_command"

    def test_invalid_params(self) -> None:
        """Params the command does not accept are invalid_params."""
        with pytest.raises(ApiError) as err:
            _create({"command": "scan", "params": {"bogus": 1}})
        assert err.value.code == "invalid_params"

    def test_privileged_goes_to_the_daemon(self) -> None:
        """A privileged command is forwarded to the daemon unchanged."""
        accepted = Reply(HTTPStatus.ACCEPTED)
        with patch(f"{_PKG}.run_privileged", return_value=accepted) as run:
            got = _create({"command": "gaming-reset", "confirm_phrase": "p"})
        assert got is accepted
        run.assert_called_once_with("gaming-reset", {}, "p")

    def test_plain_job_is_created(self) -> None:
        """A plain command creates a job and answers 201 with it."""
        with (
            patch(f"{_PKG}.create_job", return_value="j1") as create,
            patch(f"{_PKG}.read_job", return_value={"id": "j1"}),
        ):
            got = _create({"command": "scan", "confirm_phrase": "p"})
        create.assert_called_once_with("scan", {}, confirm_phrase="p")
        assert (got.status, got.payload) == (HTTPStatus.CREATED, {"id": "j1"})

    def test_store_refusal(self) -> None:
        """A job store refusal surfaces its error code."""
        with (
            patch(f"{_PKG}.create_job", side_effect=JobError("m", code="busy")),
            pytest.raises(ApiError) as err,
        ):
            _create({"command": "scan"})
        assert err.value.code == "busy"


class TestAnswerAndCancel:
    """Answering a job prompt and cancelling a job."""

    def test_answer(self) -> None:
        """A valid answer is written and answers 204."""
        body = {"prompt_id": "q", "value": "v"}
        with patch(f"{_PKG}.write_answer") as write:
            reply = _web_jobs.answer_view(make_request("j", body=body))
        write.assert_called_once_with("j", "q", "v")
        assert reply.status == HTTPStatus.NO_CONTENT

    @pytest.mark.parametrize("body", [{}, {"prompt_id": "q", "value": 1}])
    def test_answer_body_is_validated(self, body: dict[str, Any]) -> None:
        """A missing prompt id or non-string value is invalid_params."""
        with pytest.raises(ApiError) as err:
            _web_jobs.answer_view(make_request("j", body=body))
        assert err.value.code == "invalid_params"

    def test_answer_refusal(self) -> None:
        """Answering a missing job is not_found."""
        body = {"prompt_id": "q", "value": "v"}
        with pytest.raises(ApiError) as err:
            _web_jobs.answer_view(make_request("missing", body=body))
        assert err.value.code == "not_found"

    def test_cancel(self) -> None:
        """Cancelling a job calls cancel and answers 204."""
        with patch(f"{_PKG}.cancel") as cancel:
            reply = _web_jobs.cancel_view(make_request("j"))
        cancel.assert_called_once_with("j")
        assert reply.status == HTTPStatus.NO_CONTENT

    def test_cancel_refusal(self) -> None:
        """Cancelling a missing job is not_found."""
        with pytest.raises(ApiError) as err:
            _web_jobs.cancel_view(make_request("missing"))
        assert err.value.code == "not_found"


class TestRestoreBackup:
    """Restoring a state backup through a confirmed job."""

    def _restore(self, phrase: str, backup_id: str = _BACKUP.id) -> Reply:
        with (
            patch(f"{_PKG}.list_backups", return_value=[_BACKUP]),
            patch(f"{_PKG}.create_job", return_value="j1") as create,
            patch(f"{_PKG}.read_job", return_value={"id": "j1"}),
        ):
            reply = _web_jobs.restore_backup_view(
                make_request(backup_id, body={"confirm_phrase": phrase})
            )
        create.assert_called_once_with(
            "restore-backup", {"backup_id": backup_id}, confirm_phrase=phrase
        )
        return reply

    def test_restores_with_the_exact_phrase(self) -> None:
        """The exact restore phrase creates the restore job."""
        reply = self._restore(f"restore backup {_BACKUP.id}")
        assert payload_of(reply) == {"id": "j1"}

    def test_unknown_backup(self) -> None:
        """An unknown backup id is not_found."""
        with (
            patch(f"{_PKG}.list_backups", return_value=[]),
            pytest.raises(ApiError) as err,
        ):
            _web_jobs.restore_backup_view(make_request("zzz"))
        assert err.value.code == "not_found"

    def test_wrong_phrase(self) -> None:
        """A missing or wrong phrase is wrong_phrase."""
        with (
            patch(f"{_PKG}.list_backups", return_value=[_BACKUP]),
            pytest.raises(ApiError) as err,
        ):
            _web_jobs.restore_backup_view(make_request(_BACKUP.id))
        assert err.value.code == "wrong_phrase"

    def test_store_refusal(self) -> None:
        """A job store refusal on restore surfaces its error code."""
        phrase = f"restore backup {_BACKUP.id}"
        with (
            patch(f"{_PKG}.list_backups", return_value=[_BACKUP]),
            patch(f"{_PKG}.create_job", side_effect=JobError("m", code="locked")),
            pytest.raises(ApiError) as err,
        ):
            _web_jobs.restore_backup_view(
                make_request(_BACKUP.id, body={"confirm_phrase": phrase})
            )
        assert err.value.code == "locked"
