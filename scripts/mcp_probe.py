#!/usr/bin/env python3
"""Fail unless the MCP server answers an ``initialize`` request over stdio.

``scripts/deploy.sh`` runs this as a health check. It starts the server the
way Claude Code does (``<venv python> -m steam_backlog_enforcer._mcp``, see
the repo-root ``.mcp.json``), sends one JSON-RPC ``initialize`` line, closes
stdin, and requires a response whose ``result.serverInfo.name`` is the
expected server name. An import error, a crash, a hang or a wrong answer all
exit 1 with the reason on stderr.

Usage::

    python3 scripts/mcp_probe.py --python ~/.venvs/steam-backlog-mcp/bin/python \
        --repo ~/src/vapor
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

_EXPECTED_NAME = "steam-backlog-enforcer"
_TIMEOUT_SECONDS = 20
_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    },
}


class ProbeError(Exception):
    """The server did not answer ``initialize`` as expected."""


def _run_server(python: Path, repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the server with one request on stdin; return its finished process."""
    try:
        return subprocess.run(
            [str(python), "-m", "steam_backlog_enforcer._mcp"],
            input=json.dumps(_REQUEST) + "\n",
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        msg = f"interpreter not found: {python}"
        raise ProbeError(msg) from exc
    except subprocess.TimeoutExpired as exc:
        msg = f"server did not exit within {_TIMEOUT_SECONDS}s"
        raise ProbeError(msg) from exc


def _server_name(stdout: str) -> str | None:
    """Return ``result.serverInfo.name`` of the id-1 response, if any."""
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict) or message.get("id") != 1:
            continue
        result = message.get("result")
        info = result.get("serverInfo") if isinstance(result, dict) else None
        name = info.get("name") if isinstance(info, dict) else None
        return name if isinstance(name, str) else None
    return None


def probe(python: Path, repo: Path) -> str:
    """Return the server's name, or raise :class:`ProbeError`."""
    proc = _run_server(python, repo)
    name = _server_name(proc.stdout)
    if name is None:
        tail = proc.stderr.strip().splitlines()[-1:] or ["(no stderr)"]
        msg = f"no initialize response (exit {proc.returncode}): {tail[0]}"
        raise ProbeError(msg)
    if name != _EXPECTED_NAME:
        msg = f"serverInfo.name is {name!r}, not {_EXPECTED_NAME!r}"
        raise ProbeError(msg)
    return name


def main() -> int:
    """Parse arguments, probe the server, report the outcome."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    try:
        name = probe(args.python, args.repo)
    except ProbeError as exc:
        sys.stderr.write(f"mcp_probe: FAIL: {exc}\n")
        return 1
    sys.stdout.write(f"mcp_probe: {name} answered initialize\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
