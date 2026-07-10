# Steam Backlog Enforcer

Forces you to 100% complete one Steam game at a time before moving on.

## Features

- **Achievement tracking**: Picks the next game by shortest HLTB completionist time
- **Store blocking**: Blocks `store.steampowered.com` via `/etc/hosts`
- **Game uninstalling**: Removes all installed games except the assigned one
- **Process enforcement**: Kills unauthorized game processes
- **Tampering detection**: Detects achievement unlocks on non-assigned games
- **HLTB integration**: Estimates completion time with persistent cache

## Setup

```bash
python -m python_pkg.steam_backlog_enforcer.main setup
```

## Commands

| Command     | Description                                |
| ----------- | ------------------------------------------ |
| `scan`      | Scan library, fetch HLTB data, assign game |
| `check`     | Check if assigned game is complete         |
| `status`    | Show current assignment and blocking       |
| `list`      | List incomplete games from snapshot        |
| `skip`      | Skip the currently assigned game           |
| `enforce`   | Run enforcer (block, uninstall, kill)      |
| `unblock`   | Remove store blocking                      |
| `reset`     | Reset all state                            |
| `installed` | List currently installed Steam games       |
| `uninstall` | Interactively uninstall non-assigned games |
| `setup`     | First-time configuration                   |

## Enforce mode

```bash
sudo python -m python_pkg.steam_backlog_enforcer.main enforce
```

This will:

1. Block Steam store in `/etc/hosts`
2. Uninstall all games except the assigned one
3. Continuously kill any unauthorized game processes

## Game Uninstall

Directly removes appmanifest files and game directories from `~/.local/share/Steam/steamapps/`.
Preserves Proton versions and Steam Linux Runtime.

```bash
python -m python_pkg.steam_backlog_enforcer.main uninstall
```

## MCP server (Claude Code integration)

The enforcer exposes an MCP server (`steam_backlog_enforcer._mcp`) so Claude Code
and its subagents can query the backlog and drive it through typed tools.

- **Read tools:** `get_dataset`, `get_status`, `get_stats`, `list_backlog`.
- **Gated write tools:** `pick_manual`, `block_gaming` — each defaults to a
  dry-run **preview**; pass `confirm=true` to actually apply. These write tools
  must **never** be added to a permission allowlist (a subagent could otherwise
  bypass the human confirmation).

The `mcp` SDK is an optional dependency (`pip install -e '.[mcp]'`), kept out of
the CLI/systemd system-python path. One-time setup of the dedicated venv that
Claude Code spawns:

```bash
./scripts/setup_mcp.sh
```

Registration lives in the checked-in [`.mcp.json`](./.mcp.json) (project scope).
Restart Claude Code in this repo and approve the project MCP-server prompt for it
to load. Verify with `claude mcp list`.
