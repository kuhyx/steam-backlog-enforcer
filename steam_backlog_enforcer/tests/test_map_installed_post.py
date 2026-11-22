"""``map-installed``: what ``POST /api/jobs`` refuses before a job exists."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._command_params import InvalidParamsError
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._post_job import assert_refused, post_job

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def _post(
    phrase: str | None, appids: str = "10,30", *, running: bool = False
) -> tuple[object, MagicMock]:
    checked = patch(
        "steam_backlog_enforcer._compat_view.checked_appids",
        side_effect=lambda raw: (
            [int(x) for x in str(raw).split(",") if x.isdigit()] or _bad()
        ),
    )
    return post_job(
        "map-installed", {"appids": appids}, phrase, running=running, extra=[checked]
    )


def _bad() -> list[int]:
    msg = "not installed"
    raise InvalidParamsError(msg)


class TestPostTimeFriction:
    """``POST /api/jobs`` refuses before a job exists."""

    @pytest.mark.parametrize("phrase", [None, "map 3 games", "Map 2 games"])
    def test_wrong_phrase_creates_no_job(self, phrase: str | None) -> None:
        """The count is part of the phrase: a stale count is wrong."""
        assert_refused(*_post(phrase), "wrong_phrase")

    def test_game_running_is_409(self) -> None:
        """The right phrase while a game runs: ``game_running``, no job."""
        assert_refused(
            *_post("map 2 games", running=True), "game_running", HTTPStatus.CONFLICT
        )

    def test_bad_appids_are_invalid_params(self) -> None:
        """Ids that are not installed games: 400 before the phrase."""
        assert_refused(*_post("map 0 games", appids="x"), "invalid_params")

    def test_unreadable_steam_is_op_failed(self) -> None:
        """Steam's library cannot be read: ``op_failed`` before a job exists."""
        unreadable = patch(
            "steam_backlog_enforcer._compat_view.checked_appids",
            side_effect=OSError("no library"),
        )
        reply, create = post_job(
            "map-installed", {"appids": "10"}, "map 1 games", extra=[unreadable]
        )
        assert_refused(reply, create, "op_failed")

    def test_right_phrase_creates_the_job(self) -> None:
        """Right phrase, no game: the job, with the phrase passed on."""
        reply, create = _post("map 2 games")
        assert not isinstance(reply, ApiError)
        create.assert_called_once_with(
            "map-installed", {"appids": "10,30"}, confirm_phrase="map 2 games"
        )
