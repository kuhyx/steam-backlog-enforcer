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
    daily_gaming_seconds: int = 8 * 3600
    """Gaming seconds allowed per gaming day, which starts at 06:00 local.

    Spending this budget shuts Steam down and masks the launcher binaries until
    the next 06:00. See :mod:`steam_backlog_enforcer._playtime`.
    """
    count_launcher_processes: bool = True
    """Whether time spent in non-Steam launchers counts against the budget.

    Set False if a launcher legitimately idles in the tray all day. Leaving it
    True is the safer default: under-counting is the failure mode that quietly
    defeats the budget entirely.
    """
    counted_processes: list[dict[str, Any]] | None = None
    """Non-Steam games that count against the budget, beyond the launcher set.

    Each entry is ``{"id": ..., "label": ..., "names": [...]}``. ``None`` means
    "use the built-in defaults" (osu!lazer); an explicit ``[]`` means "none",
    which is why this is not simply an empty list. Parsed and validated by
    :mod:`steam_backlog_enforcer._counted_procs` — the field exists here only so
    that ``save()`` round-trips a hand-edited list instead of dropping it.

    Deliberately separate from ``LAUNCHER_PROCESS_NAMES``: that frozenset is
    also the total-block kill list, so adding a game there has side effects
    this list does not.
    """
    playtime_enforcement: bool = True
    """Master switch for the daily gaming budget.

    Disabling stops the cutoff but never strands a live block — the release
    path runs regardless, so "disabled" cannot come to mean "blocked forever".
    """
    # Engagement gating: without it a resident game process bills the budget
    # while the screen is locked. See :mod:`_playtime_engagement`.
    engagement_gate: bool = True
    """Whether a tick must show active engagement before it bills."""
    idle_grace_seconds: int = 300
    """Input silence before billing stops; controller input counts as input."""
    require_game_focus: bool = True
    """Whether the focused window must belong to the game for a tick to bill."""

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
            json.dumps(self.__dict__, indent=2) + "\n",
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
