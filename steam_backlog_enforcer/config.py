"""Configuration management for Steam Backlog Enforcer."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
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

logger = logging.getLogger(__name__)


def _atomic_write(path: Path, data: str) -> None:
    """Write data to a file atomically via a temporary file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        tmp_path.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


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
        _atomic_write(
            CONFIG_FILE,
            json.dumps(self.__dict__, indent=2) + "\n",
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
        _atomic_write(
            STATE_FILE,
            json.dumps(self.__dict__, indent=2) + "\n",
        )

    @classmethod
    def load(cls) -> State:
        """Load state from disk, or return defaults."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, ValueError):
                logger.warning("Corrupt state file, using defaults.")
                return cls()
            return cls(
                **{k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            )
        return cls()


def save_snapshot(data: list[dict[str, Any]]) -> None:
    """Save an achievement snapshot to disk."""
    _atomic_write(
        SNAPSHOT_FILE,
        json.dumps(data, indent=2) + "\n",
    )


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
