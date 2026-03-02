"""Configuration management for Steam Backlog Enforcer."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "steam_backlog_enforcer"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "state.json"
SNAPSHOT_FILE = CONFIG_DIR / "snapshot.json"
LOG_FILE = CONFIG_DIR / "enforcer.log"

# Steam store domains to block.
BLOCKED_DOMAINS = [
    "store.steampowered.com",
    "checkout.steampowered.com",
    "store.akamai.steamstatic.com",
    "storefront.steampowered.com",
    "store.cloudflare.steamstatic.com",
]

HOSTS_FILE = Path("/etc/hosts")


@dataclass
class Config:
    """User configuration."""

    steam_api_key: str = ""
    steam_id: str = ""
    skip_app_ids: list[int] = field(default_factory=list)
    block_store: bool = True
    kill_unauthorized_games: bool = True
    uninstall_other_games: bool = True
    desktop_notifications: bool = True

    def save(self) -> None:
        """Persist config to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(self.__dict__, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls) -> Config:
        """Load config from disk, or return defaults."""
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cls(
                **{k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            )
        return cls()


@dataclass
class State:
    """Persistent state across runs."""

    current_app_id: int | None = None
    current_game_name: str = ""
    finished_app_ids: list[int] = field(default_factory=list)

    def save(self) -> None:
        """Persist state to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(self.__dict__, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls) -> State:
        """Load state from disk, or return defaults."""
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return cls(
                **{k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            )
        return cls()


def save_snapshot(data: list[dict[str, Any]]) -> None:
    """Save an achievement snapshot to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_snapshot() -> list[dict[str, Any]] | None:
    """Load the cached achievement snapshot, or None if absent."""
    if SNAPSHOT_FILE.exists():
        result: list[dict[str, Any]] = json.loads(
            SNAPSHOT_FILE.read_text(encoding="utf-8")
        )
        return result
    return None


def interactive_setup() -> Config:
    """Run first-time interactive setup."""
    api_key = input("Enter your Steam Web API key: ").strip()
    if not api_key:
        sys.exit(1)

    steam_id = input("Enter your Steam64 ID: ").strip()
    if not steam_id:
        sys.exit(1)

    config = Config(steam_api_key=api_key, steam_id=steam_id)
    config.save()
    CONFIG_FILE.chmod(0o600)
    return config
