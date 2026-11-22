"""File a failed store check as a task in kuhy's todo app (local MCP server).

Runs as the desktop user (web server or CLI), who owns the todo token; the
root daemon only builds the report. Stdlib only: a minimal MCP
streamable-HTTP client (initialize, ``Mcp-Session-Id``, ``tools/call``).

One task per failure kind: when an open task with the same title exists,
nothing is filed or appended. Any failure to reach the server raises
:class:`FilingError`, so the caller can fail loudly instead of quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO: Final = "kuhyx/steam-backlog-enforcer"
DEFAULT_URL: Final = "http://127.0.0.1:8735/mcp"
_PROTOCOL: Final = "2025-03-26"
_TIMEOUT_SECONDS: Final = 10.0
_COLUMNS: Final = 5
_HTTP_ERROR: Final = 400


class FilingError(Exception):
    """The todo MCP server could not be reached or refused the call."""


@dataclass(frozen=True)
class Filed:
    """What filing did: ``created`` a task, or found ``existing`` open one."""

    created: bool
    task: str


def _settings(env: Mapping[str, str]) -> tuple[str, Path]:
    """The MCP URL and token file (``SBE_TODO_MCP_URL`` / ``SBE_TODO_TOKEN_FILE``)."""
    url = env.get("SBE_TODO_MCP_URL") or DEFAULT_URL
    default_token = Path.home() / ".config" / "todo-mcp-client" / "token"
    return url, Path(env.get("SBE_TODO_TOKEN_FILE") or default_token)


class _Mcp:
    """One MCP session over streamable HTTP."""

    def __init__(self, url: str, token: str) -> None:
        if not url.startswith(("http://", "https://")):
            msg = f"unsupported MCP url: {url}"
            raise FilingError(msg)
        self._url = url
        self._token = token
        self._session: str | None = None
        self._next_id = 0

    def _post(self, payload: dict[str, Any]) -> tuple[str, str, str | None]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        parts = urlsplit(self._url)
        conn_type = (
            http.client.HTTPSConnection
            if parts.scheme == "https"
            else http.client.HTTPConnection
        )
        conn = conn_type(parts.netloc, timeout=_TIMEOUT_SECONDS)
        try:
            conn.request("POST", parts.path or "/", json.dumps(payload), headers)
            reply = conn.getresponse()
            body = reply.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException) as err:
            msg = f"todo MCP {self._url} unreachable: {err}"
            raise FilingError(msg) from err
        finally:
            conn.close()
        if reply.status >= _HTTP_ERROR:
            msg = f"todo MCP {self._url}: HTTP {reply.status}"
            raise FilingError(msg)
        ctype = reply.getheader("Content-Type", "")
        return ctype, body, reply.getheader("Mcp-Session-Id")

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        ctype, body, session = self._post(payload | {"params": params})
        if method == "initialize":
            self._session = session
        message = _parse(ctype, body)
        if "error" in message:
            msg = f"todo MCP {method}: {message['error']}"
            raise FilingError(msg)
        return message.get("result", {})

    def call(self, tool: str, arguments: dict[str, object]) -> str:
        """Call *tool*; its text, or :class:`FilingError` if it reports one."""
        if self._next_id == 0:
            info = {"name": "steam-backlog-enforcer", "version": "1"}
            self._rpc(
                "initialize",
                {"protocolVersion": _PROTOCOL, "capabilities": {}, "clientInfo": info},
            )
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        text = "\n".join(
            part.get("text", "")
            for part in result.get("content", [])
            if part.get("type") == "text"
        )
        if result.get("isError"):
            msg = f"todo MCP {tool}: {text}"
            raise FilingError(msg)
        return text


def _parse(ctype: str, body: str) -> dict[str, Any]:
    """The JSON-RPC message in a JSON or server-sent-events reply."""
    rows = [body]
    if "text/event-stream" in ctype:
        rows = [r.removeprefix("data:").strip() for r in body.splitlines()]
    for raw in rows:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            return message
    msg = f"todo MCP sent an unparsable reply: {body[:80]!r}"
    raise FilingError(msg)


def _open_task(listing: str, title: str) -> str | None:
    """The id of an open task in *listing* titled *title*.

    The server lists a new note as ``<repo name> todos: <title>``, so the
    title matches exactly or as that suffix.
    """
    for row in listing.splitlines():
        parts = row.split("\t")
        if len(parts) < _COLUMNS:
            continue
        listed = re.sub(r"^#+\s*", "", parts[4].strip())
        if listed == title or listed.endswith(f": {title}"):
            return parts[0]
    return None


def file_report(
    report: Mapping[str, object], env: Mapping[str, str] | None = None
) -> Filed:
    """File *report* (``title`` + ``body``) unless an open task has its title.

    Raises:
        FilingError: No token, the server is unreachable, or a call failed.
    """
    url, token_file = _settings(os.environ if env is None else env)
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        msg = f"no todo MCP token at {token_file}: {exc}"
        raise FilingError(msg) from exc
    title = str(report["title"])
    client = _Mcp(url, token)
    existing = _open_task(
        client.call("list_tasks", {"repo": REPO, "status": "open"}), title
    )
    if existing is not None:
        return Filed(created=False, task=existing)
    reply = client.call(
        "add_task",
        {
            "repo": REPO,
            "title": title,
            "body": str(report["body"]),
            "done_check": "none",
            "priority": "medium",
            "new_note": True,
        },
    )
    return Filed(created=True, task=reply.split("\n", 1)[0])
