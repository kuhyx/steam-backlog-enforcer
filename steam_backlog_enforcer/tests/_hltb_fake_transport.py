"""Fake aiohttp transport for HLTB search tests: no request leaves the process."""

from __future__ import annotations

import json
from typing import Any, Self

MATCH = {
    "data": [
        {
            "game_name": "Vox Populi",
            "game_alias": "",
            "game_type": "game",
            "game_id": 77,
            "comp_100": 36000,
            "comp_100_count": 42,
            "count_comp": 300,
        }
    ]
}
NO_MATCH: dict[str, Any] = {"data": []}


class FakeResp:
    """Minimal aiohttp response stand-in."""

    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        """Store the canned status and JSON body (``None`` = not JSON)."""
        self.status = status
        self._body = body

    async def __aenter__(self) -> Self:
        """Enter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit."""

    async def json(self) -> dict[str, Any]:
        """Return the body, or fail like a garbage payload would."""
        if self._body is None:
            msg = "Expecting value"
            raise json.JSONDecodeError(msg, "<html>", 0)
        return self._body


class FakeSession:
    """Fake session routing each search POST by its first search term."""

    def __init__(self, routes: dict[str, object]) -> None:
        """Map a query's first word to a _Resp or an exception to raise."""
        self.routes = routes
        self.posts: list[str] = []

    def post(self, _url: str, *, headers: object, data: str) -> FakeResp:
        """Return (or raise) the canned outcome for this query."""
        del headers
        terms = json.loads(data)["searchTerms"]
        query = " ".join(terms)
        self.posts.append(query)
        outcome = self.routes.get(query, self.routes.get("*"))
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, FakeResp)
        return outcome


class FakeInitSession:
    """Fake ClientSession: GET /init answers ``status``; POSTs use ``routes``."""

    def __init__(self, status: int | BaseException, routes: dict[str, object]) -> None:
        """Store the canned init outcome and search routes."""
        self.status = status
        self.search = FakeSession(routes)
        self.gets = 0

    async def __aenter__(self) -> Self:
        """Enter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit."""

    def get(self, *_a: object, **_k: object) -> FakeResp:
        """Answer the auth init."""
        self.gets += 1
        if isinstance(self.status, BaseException):
            raise self.status
        return FakeResp(self.status, {"token": "tok"})

    def post(self, url: str, *, headers: object, data: str) -> FakeResp:
        """Delegate searches."""
        return self.search.post(url, headers=headers, data=data)
