"""Configuration management for Steam Backlog Enforcer."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from steam_backlog_enforcer._config_groups import (
    AssignmentTimes,
    EarnSources,
    LegacyManualPick,
    PlaytimePolicy,
)
from steam_backlog_enforcer._flat_record import flat_group, from_flat, to_flat
from steam_backlog_enforcer._state_migrations import (
    backfill_assignment_times,
    migrate_legacy_manual_pick,
)

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


def _atomic_write(path: Path, data: str, *, mode: int | None = None) -> None:
    """Write data to a file atomically via a temporary file + rename.

    Args:
        path: Destination file.
        data: Text to write.
        mode: Permission bits for the result. ``None`` keeps ``mkstemp``'s
            0600, which is what files holding secrets (``config.json`` carries
            ``steam_api_key``) must stay at. Callers whose file has to be
            readable by an unprivileged reader pass it explicitly; it is set on
            the temporary file so the mode lands with the rename rather than
            leaving a window where the destination exists at 0600.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        os.write(fd, data.encode("utf-8"))
        if mode is not None:
            os.fchmod(fd, mode)
        # Keep the owner, or a root daemon write locks the user's CLI out.
        with contextlib.suppress(OSError):  # absent file / non-root: skip
            original = path.stat()
            os.fchown(fd, original.st_uid, original.st_gid)
        os.close(fd)
        tmp_path.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


# The public name, for callers outside this module. The private one predates
# it and is still what most of the package imports (and what tests patch).
atomic_write = _atomic_write


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
    earn: EarnSources = field(
        default_factory=EarnSources, metadata=flat_group(EarnSources)
    )
    playtime: PlaytimePolicy = field(
        default_factory=PlaytimePolicy, metadata=flat_group(PlaytimePolicy)
    )

    def save(self) -> None:
        """Persist config to disk."""
        _atomic_write(
            CONFIG_FILE,
            json.dumps(to_flat(self), indent=2) + "\n",
        )

    @classmethod
    def load(cls) -> Config:
        """Load config from disk, or return defaults."""
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return from_flat(cls, data)
        return cls()


@dataclass
class State:
    """Persistent state across runs."""

    current_app_id: int | None = None
    current_game_name: str = ""
    finished_app_ids: list[int] = field(default_factory=list)
    skipped_until: dict[str, str] = field(default_factory=dict)
    """Map of ``str(app_id)`` → ISO-8601 UTC timestamp when the skip expires.

    Games in this map are excluded from auto-assignment until the timestamp
    elapses. Populated when the user declines a freshly-picked game via the
    interactive prompt in ``cmd_done``.
    """
    enforcement_started_at: str = ""
    """ISO-8601 UTC timestamp set on the first game assignment."""
    legacy_pick: LegacyManualPick = field(
        default_factory=LegacyManualPick,
        metadata=flat_group(LegacyManualPick, "manual_pick_"),
    )
    manual_picks: list[dict[str, Any]] = field(default_factory=list)
    """Manual picks, newest last; inactive ones stay until a new choice.

    Each entry is ``{"app_id": int, "game_name": str, "started_at": iso}``,
    plus ``"released_at": iso`` once it earned a new achievement. Plain dicts
    because ``save`` serialises them straight to JSON.
    """
    assignment: AssignmentTimes = field(
        default_factory=AssignmentTimes, metadata=flat_group(AssignmentTimes)
    )
    store_unblocked_until: str = ""
    """ISO deadline of the open store window (``unblock``); CLI-written only."""

    def skip_for_days(self, app_id: int, days: int) -> None:
        """Mark ``app_id`` as skipped for ``days`` days from now (UTC)."""
        expires = datetime.now(UTC) + timedelta(days=days)
        self.skipped_until[str(app_id)] = expires.isoformat()

    def active_skipped_ids(self) -> set[int]:
        """Return currently-skipped app IDs and prune expired entries.

        Mutates ``self.skipped_until`` to drop expired or malformed entries.
        Callers should ``save()`` if they want the prune persisted.
        """
        now = datetime.now(UTC)
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
            json.dumps(to_flat(self), indent=2) + "\n",
        )

    @classmethod
    def load(cls) -> State:
        """Load state from disk, or return defaults."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError, OSError, ValueError:
                logger.warning("Corrupt state file, using defaults.")
                return cls()
            state = from_flat(cls, data)
            migrated = migrate_legacy_manual_pick(state)
            if backfill_assignment_times(state) or migrated:
                state.save()
            return state
        return cls()
