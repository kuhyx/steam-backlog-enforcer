"""Tests for filing failed store checks in the todo app (against a fake MCP)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._todo_filing import (
    FilingError,
    _Mcp,
    _parse,
    _settings,
    file_report,
)
from steam_backlog_enforcer.tests._fake_todo_mcp import FakeTodo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_REPORT = {
    "title": "Store unblock verification failed: hosts",
    "body": "Time: t\nAction: unblock\n",
}


@pytest.fixture(name="todo")
def fixture_todo() -> Iterator[FakeTodo]:
    """A running fake todo MCP server."""
    server = FakeTodo(0, "tok")
    server.start()
    yield server
    server.shutdown()
    server.server_close()


_GOOD = "tok"


def _env(todo: FakeTodo, tmp_path: Path, secret: str = _GOOD) -> dict[str, str]:
    token_file = tmp_path / "token"
    token_file.write_text(f"{secret}\n", encoding="utf-8")
    return {"SBE_TODO_MCP_URL": todo.url, "SBE_TODO_TOKEN_FILE": str(token_file)}


def test_files_one_task_with_report(todo: FakeTodo, tmp_path: Path) -> None:
    """A new failure is filed once: repo, title, body, done_check none."""
    filed = file_report(_REPORT, _env(todo, tmp_path))
    assert filed.created
    assert filed.task.startswith("added ")
    [task] = todo.tasks
    assert task["repo"] == "kuhyx/steam-backlog-enforcer"
    assert task["title"] == _REPORT["title"]
    assert task["body"] == _REPORT["body"]
    assert task["done_check"] == "none"
    assert task["priority"] == "medium"
    assert task["new_note"] is True


def test_open_task_with_same_title_files_nothing(
    todo: FakeTodo, tmp_path: Path
) -> None:
    """The second identical failure finds the open task and adds nothing."""
    env = _env(todo, tmp_path)
    file_report(_REPORT, env)
    again = file_report(_REPORT, env)
    assert not again.created
    assert again.task == "00000001"
    assert len(todo.tasks) == 1
    assert todo.calls == ["list_tasks", "add_task", "list_tasks"]


def test_other_title_is_filed(todo: FakeTodo, tmp_path: Path) -> None:
    """A different check is a different task."""
    env = _env(todo, tmp_path)
    file_report(_REPORT, env)
    file_report(_REPORT | {"title": "Store unblock verification failed: https"}, env)
    assert len(todo.tasks) == 2


def test_server_down_raises(tmp_path: Path) -> None:
    """No server listening is a FilingError, never a silent pass."""
    server = FakeTodo(0, "tok")
    env = _env(server, tmp_path)
    server.server_close()
    with pytest.raises(FilingError, match="unreachable"):
        file_report(_REPORT, env)


def test_bad_token_raises(todo: FakeTodo, tmp_path: Path) -> None:
    """A rejected token is a FilingError naming the HTTP status."""
    with pytest.raises(FilingError, match="HTTP 401"):
        file_report(_REPORT, _env(todo, tmp_path, "wrong"))


def test_missing_token_file_raises(todo: FakeTodo, tmp_path: Path) -> None:
    """No token file is a FilingError."""
    env = {"SBE_TODO_MCP_URL": todo.url, "SBE_TODO_TOKEN_FILE": str(tmp_path / "x")}
    with pytest.raises(FilingError, match="no todo MCP token"):
        file_report(_REPORT, env)


def test_defaults_point_at_live_server() -> None:
    """Without env the filer targets the local todo MCP and kuhy's token."""
    url, token = _settings({})
    assert url == "http://127.0.0.1:8735/mcp"
    assert token.parts[-2:] == ("todo-mcp-client", "token")


def test_unsupported_url_raises() -> None:
    """Only http(s) URLs are accepted."""
    with pytest.raises(FilingError, match="unsupported"):
        _Mcp("file:///x", "t")


@pytest.mark.parametrize(
    ("ctype", "body"),
    [("application/json", "not json"), ("text/event-stream", "data: [1]")],
)
def test_unparsable_reply_raises(ctype: str, body: str) -> None:
    """A reply with no JSON-RPC object in it is a FilingError."""
    with pytest.raises(FilingError, match="unparsable"):
        _parse(ctype, body)


def _reply(message: dict[str, object]) -> tuple[str, str, None]:
    return "application/json", json.dumps(message), None


def test_rpc_error_raises() -> None:
    """A JSON-RPC error answer is a FilingError naming the method."""
    error = _reply({"jsonrpc": "2.0", "id": 1, "error": {"message": "boom"}})
    with (
        patch.object(_Mcp, "_post", return_value=error),
        pytest.raises(FilingError, match="initialize"),
    ):
        _Mcp("http://127.0.0.1:9/mcp", "t").call("list_tasks", {})


def test_tool_error_raises() -> None:
    """A tool that reports isError is a FilingError with its text."""
    ok = _reply({"jsonrpc": "2.0", "id": 1, "result": {}})
    bad = _reply(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"isError": True, "content": [{"type": "text", "text": "no"}]},
        }
    )
    with (
        patch.object(_Mcp, "_post", side_effect=[ok, ok, bad]),
        pytest.raises(FilingError, match="add_task: no"),
    ):
        _Mcp("http://127.0.0.1:9/mcp", "t").call("add_task", {})
