"""A fake todo MCP server: the list_tasks / add_task subset the filer uses.

Speaks streamable HTTP like the real one (initialize hands out an
``Mcp-Session-Id``, replies as server-sent events) and keeps tasks in memory.
Run standalone for VM checks: ``python -m steam_backlog_enforcer.tests._fake_todo_mcp
<port> <token> <dump.json>``; every add is also written to the dump file.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from typing import Any


class FakeTodo(ThreadingHTTPServer):
    """The server plus its task list."""

    def __init__(self, port: int, token: str, dump: Path | None = None) -> None:
        """Listen on 127.0.0.1:*port* (0 picks one)."""
        super().__init__(("127.0.0.1", port), _Handler)
        self.token = token
        self.dump = dump
        self.tasks: list[dict[str, Any]] = []
        self.calls: list[str] = []

    @property
    def url(self) -> str:
        """The MCP endpoint URL."""
        return f"http://127.0.0.1:{self.server_address[1]}/mcp"

    def start(self) -> None:
        """Serve in a daemon thread."""
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    def tool(self, name: str, args: dict[str, Any]) -> str:
        """Answer one tool call the way the real server words it."""
        self.calls.append(name)
        if name == "list_tasks":
            rows = [
                f"{t['id'][:8]}\ttodo\t{t['priority']}\t{t['repo']}\t{t['title']}\tclaude"
                for t in self.tasks
                if t["repo"] == args.get("repo")
            ]
            return "\n".join(rows) or "no tasks match"
        task = dict(args) | {"id": f"{len(self.tasks) + 1:08d}deadbeef"}
        self.tasks.append(task)
        if self.dump is not None:
            self.dump.write_text(json.dumps(self.tasks, indent=2), encoding="utf-8")
        return f"added {task['id']}\n{task['id'][:8]}\ttodo\tmedium\t{task['repo']}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeTodo

    def log_message(self, *_args: object) -> None:
        """Stay quiet."""

    def do_POST(self) -> None:
        """One JSON-RPC message in, one SSE event out."""
        if self.headers.get("Authorization") != f"Bearer {self.server.token}":
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        message = json.loads(self.rfile.read(length))
        if "id" not in message:  # A notification.
            self.send_response(202)
            self.end_headers()
            return
        params = message.get("params", {})
        if message["method"] == "initialize":
            result: dict[str, Any] = {"protocolVersion": params["protocolVersion"]}
        else:
            text = self.server.tool(params["name"], params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": text}]}
        body = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Mcp-Session-Id", "fake-session")
        self.end_headers()
        self.wfile.write(f"event: message\ndata: {body}\n\n".encode())


if __name__ == "__main__":
    FakeTodo(int(sys.argv[1]), sys.argv[2], Path(sys.argv[3])).serve_forever()
