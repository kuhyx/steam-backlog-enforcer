"""Timestamped backups of ``state.json``, taken before destructive commands.

``reset`` wipes the assignment, finished list and pick history; a backup is
taken automatically first so a mistyped command costs nothing. Restoring is
itself destructive (it replaces the current state), so the current state is
backed up before every restore as well.

Only ``state.json`` is copied. The lock and exception files
(``total_block_lock.json``, ``approved_exceptions.json``) are deliberately
left out: restoring an old copy of either would be a way to lift a lock.
For the same reason the restore command is gated like ``reset`` — no restore
while a manual-pick or total-block lock is active.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import secrets
import shutil

from steam_backlog_enforcer import config as config_mod

BACKUPS_DIR = Path.home() / ".local" / "state" / "steam-backlog-enforcer" / "backups"
_STATE_NAME = "state.json"
_META_NAME = "meta.json"
_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")


@dataclass(frozen=True)
class StateBackup:
    """One backup, shaped like the TS ``StateBackup`` contract type.

    Attributes:
        id: Sortable id: UTC timestamp plus a random suffix.
        created_at: ISO-8601 UTC creation time.
        reason: Why it was taken (``"before reset"``, ...).
        size_bytes: Size of the backed-up ``state.json``.
    """

    id: str
    created_at: str
    reason: str
    size_bytes: int

    def to_json(self) -> dict[str, object]:
        """Return the JSON object the web API serves."""
        return asdict(self)


class BackupError(Exception):
    """A backup could not be found, read or restored."""


def _backup_dir(backup_id: str) -> Path:
    """Resolve a backup id to its directory, refusing anything path-like."""
    if not _ID_PATTERN.fullmatch(backup_id):
        msg = f"Not a backup id: {backup_id!r}"
        raise BackupError(msg)
    return BACKUPS_DIR / backup_id


def create_backup(reason: str) -> StateBackup | None:
    """Copy the current ``state.json`` into a new backup.

    Args:
        reason: Short human text stored with the backup.

    Returns:
        The new backup, or ``None`` when there is no state file to back up.
    """
    source = config_mod.STATE_FILE
    if not source.exists():
        return None
    now = datetime.now(UTC)
    backup_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    target = BACKUPS_DIR / backup_id
    target.mkdir(parents=True, mode=0o700)
    shutil.copy2(source, target / _STATE_NAME)
    meta = {"created_at": now.isoformat(), "reason": reason}
    (target / _META_NAME).write_text(json.dumps(meta) + "\n", encoding="utf-8")
    return _read_backup(target)


def _read_backup(path: Path) -> StateBackup | None:
    """Load one backup directory, or ``None`` if it is incomplete."""
    try:
        meta = json.loads((path / _META_NAME).read_text(encoding="utf-8"))
        size = (path / _STATE_NAME).stat().st_size
    except OSError, ValueError:
        return None
    return StateBackup(
        id=path.name,
        created_at=str(meta.get("created_at", "")),
        reason=str(meta.get("reason", "")),
        size_bytes=size,
    )


def list_backups() -> list[StateBackup]:
    """Return every readable backup, newest first."""
    if not BACKUPS_DIR.is_dir():
        return []
    found = (
        _read_backup(path)
        for path in BACKUPS_DIR.iterdir()
        if _ID_PATTERN.fullmatch(path.name)
    )
    return sorted(
        (backup for backup in found if backup is not None),
        key=lambda backup: backup.id,
        reverse=True,
    )


def restore_backup(backup_id: str) -> StateBackup | None:
    """Replace ``state.json`` with a backup's copy.

    The state being replaced is backed up first, so a restore can be undone
    by restoring that newer backup.

    Args:
        backup_id: Id from :func:`list_backups`.

    Returns:
        The backup of the state that was replaced, if there was one.

    Raises:
        BackupError: If the id is malformed or the backup is unreadable.
    """
    source = _backup_dir(backup_id) / _STATE_NAME
    try:
        data = source.read_text(encoding="utf-8")
        json.loads(data)
    except (OSError, ValueError) as exc:
        msg = f"Backup {backup_id} is unreadable: {exc}"
        raise BackupError(msg) from exc
    previous = create_backup(f"before restoring {backup_id}")
    config_mod.atomic_write(config_mod.STATE_FILE, data)
    return previous
