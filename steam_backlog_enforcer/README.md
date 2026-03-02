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
