"""MCP server entry point for the Steam Backlog Enforcer.

The tools themselves live in :mod:`steam_backlog_enforcer._mcp_query` (read
only) and :mod:`steam_backlog_enforcer._mcp_actions` (state changing); both
are imported here for their registration side effect.
"""

from __future__ import annotations

import sys

from steam_backlog_enforcer import _mcp_actions, _mcp_gaming_time, _mcp_query
from steam_backlog_enforcer._mcp_server import logger, mcp

# Imported for their @mcp.tool() registration side effect.
__all__ = ["_mcp_actions", "_mcp_gaming_time", "_mcp_query", "main", "mcp"]


def main() -> None:
    """Run the MCP server over stdio (STDOUT = JSON-RPC, STDERR = logs)."""
    logger.info(
        "Starting steam-backlog-enforcer MCP server (python=%s)", sys.executable
    )
    mcp.run()  # pragma: no cover


if __name__ == "__main__":
    main()
