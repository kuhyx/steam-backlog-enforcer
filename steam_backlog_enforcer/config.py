"""Configuration management for Steam Backlog Enforcer."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    block_store: bool = True
    kill_unauthorized_games: bool = True
    uninstall_other_games: bool = True
    desktop_notifications: bool = True
    max_manual_picks: int = 2
    """How many games may be manually locked in at once.

    All active picks stay installed and visible; the enforcer treats them as
    one allowed set. Raising this weakens enforcement proportionally.
    """

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
    skipped_until: dict[str, str] = field(default_factory=dict)
    enforcement_started_at: str = ""
    """ISO-8601 UTC timestamp set on the first game assignment."""
    """Map of ``str(app_id)`` → ISO-8601 UTC timestamp when the skip expires.

    Games in this map are excluded from auto-assignment until the timestamp
    elapses. Populated when the user declines a freshly-picked game via the
    interactive prompt in ``cmd_done``.
    """
    manual_pick_app_id: int | None = None
    manual_pick_game_name: str = ""
    manual_pick_started_at: str = ""
    """Legacy single-slot manual pick, migrated into ``manual_picks`` on load.

    Kept as fields so an older ``state.json`` still deserialises; they are
    blanked once migrated and are never written again.
    """
    manual_picks: list[dict[str, Any]] = field(default_factory=list)
    """Active manual picks, newest last.

    Each entry is ``{"app_id": int, "game_name": str, "started_at": iso}``.
    Plain dicts rather than a dataclass because ``save`` serialises
    ``self.__dict__`` straight to JSON.
    """

    def skip_for_days(self, app_id: int, days: int) -> None:
        """Mark ``app_id`` as skipped for ``days`` days from now (UTC)."""
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        self.skipped_until[str(app_id)] = expires.isoformat()

    def active_skipped_ids(self) -> set[int]:
        """Return currently-skipped app IDs and prune expired entries.

        Mutates ``self.skipped_until`` to drop expired or malformed entries.
        Callers should ``save()`` if they want the prune persisted.
        """
        now = datetime.now(timezone.utc)
        active: set[int] = set()
        to_remove: list[str] = []
        for aid_str, ts in self.skipped_until.items():
            try:
                expiry = datetime.fromisoformat(ts)
            except ValueError:
                to_remove.append(aid_str)
                continue
            if expiry > now:
                active.add(int(aid_str))
            else:
                to_remove.append(aid_str)
        for aid_str in to_remove:
            del self.skipped_until[aid_str]
        return active

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
            state = cls(
                **{k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            )
            state._migrate_legacy_manual_pick()
            return state
        return cls()

    def _migrate_legacy_manual_pick(self) -> None:
        """Fold a pre-multi-pick single manual pick into ``manual_picks``.

        A live lock written by the old single-slot code must survive the
        upgrade, so the legacy fields are read once, converted, and cleared.
        Migration happens in memory; the next ``save`` persists it.
        """
        if self.manual_pick_app_id is None or self.manual_picks:
            return
        self.manual_picks = [
            {
                "app_id": self.manual_pick_app_id,
                "game_name": self.manual_pick_game_name,
                "started_at": self.manual_pick_started_at,
            }
        ]
        self.manual_pick_app_id = None
        self.manual_pick_game_name = ""
        self.manual_pick_started_at = ""


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
