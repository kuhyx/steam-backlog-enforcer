"""Helpers shared by the ``test_web_*`` files: build a ``Request``."""

from __future__ import annotations

from email.message import Message
from typing import Any

from steam_backlog_enforcer._web_io import Reply, Request


def make_request(
    *args: str,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
) -> Request:
    """A ``Request`` with the captured path *args* and optional extras."""
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return Request(method, "/", query or {}, args, message, body or {})


def payload_of(reply: Reply) -> dict[str, Any]:
    """The JSON-object payload of *reply* (fails the test if it is not one)."""
    assert isinstance(reply.payload, dict)
    return reply.payload
