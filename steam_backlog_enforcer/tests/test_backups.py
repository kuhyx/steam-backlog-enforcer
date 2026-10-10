"""Tests for _backups: state.json snapshots taken before destructive commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from steam_backlog_enforcer import _backups as backups
from steam_backlog_enforcer import config

if TYPE_CHECKING:
    from pathlib import Path

_OLD_ID = "20260101T000000Z-aaaaaa"
_NEW_ID = "20260202T000000Z-bbbbbb"


def _write_state(text: str = '{"current_app_id": 1}') -> None:
    config.STATE_FILE.write_text(text, encoding="utf-8")


def _plant(
    backup_id: str, *, state: str | None = '{"x": 1}', meta: str | None = None
) -> Path:
    """Create a backup directory by hand; ``None`` omits that file."""
    directory = backups.BACKUPS_DIR / backup_id
    directory.mkdir(parents=True)
    if state is not None:
        (directory / "state.json").write_text(state, encoding="utf-8")
    if meta is not None:
        (directory / "meta.json").write_text(meta, encoding="utf-8")
    return directory


class TestBackupDir:
    @pytest.mark.parametrize("bad", ["", "..", "../x", "20260101T000000Z", "a/b"])
    def test_refuses_anything_that_is_not_an_id(self, bad: str) -> None:
        with pytest.raises(backups.BackupError, match="Not a backup id"):
            backups._backup_dir(bad)

    def test_resolves_a_valid_id(self) -> None:
        assert backups._backup_dir(_OLD_ID) == backups.BACKUPS_DIR / _OLD_ID


class TestCreateBackup:
    def test_no_state_file_means_no_backup(self) -> None:
        assert backups.create_backup("why") is None
        assert not backups.BACKUPS_DIR.exists()

    def test_copies_state_and_records_why(self) -> None:
        _write_state()
        backup = backups.create_backup("before reset")
        assert backup is not None
        assert backup.reason == "before reset"
        assert backup.size_bytes == len('{"current_app_id": 1}')
        copy = backups.BACKUPS_DIR / backup.id / "state.json"
        assert copy.read_text(encoding="utf-8") == '{"current_app_id": 1}'
        assert backup.to_json()["id"] == backup.id


class TestReadBackup:
    def test_missing_meta_is_unreadable(self) -> None:
        assert backups._read_backup(_plant(_OLD_ID)) is None

    def test_corrupt_meta_is_unreadable(self) -> None:
        assert backups._read_backup(_plant(_OLD_ID, meta="{nope")) is None

    def test_missing_state_is_unreadable(self) -> None:
        directory = _plant(_OLD_ID, state=None, meta="{}")
        assert backups._read_backup(directory) is None

    def test_absent_meta_fields_default_to_empty(self) -> None:
        found = backups._read_backup(_plant(_OLD_ID, meta="{}"))
        assert found is not None
        assert (found.created_at, found.reason) == ("", "")


class TestListBackups:
    def test_no_directory_is_empty(self) -> None:
        assert backups.list_backups() == []

    def test_newest_first_and_skips_junk(self) -> None:
        _plant(_OLD_ID, meta='{"reason": "old"}')
        _plant(_NEW_ID, meta='{"reason": "new"}')
        _plant("20260303T000000Z-cccccc")  # incomplete: no meta
        (backups.BACKUPS_DIR / "not-an-id").mkdir()
        assert [b.id for b in backups.list_backups()] == [_NEW_ID, _OLD_ID]


class TestRestoreBackup:
    def test_replaces_state_and_backs_up_the_old_one(self) -> None:
        _plant(_OLD_ID, state='{"current_app_id": 7}', meta="{}")
        _write_state('{"current_app_id": 1}')
        previous = backups.restore_backup(_OLD_ID)
        assert json.loads(config.STATE_FILE.read_text("utf-8")) == {"current_app_id": 7}
        assert previous is not None
        assert previous.reason == f"before restoring {_OLD_ID}"

    def test_restoring_over_no_state_has_no_previous(self) -> None:
        _plant(_OLD_ID, state="{}", meta="{}")
        assert backups.restore_backup(_OLD_ID) is None
        assert config.STATE_FILE.read_text(encoding="utf-8") == "{}"

    @pytest.mark.parametrize("state", [None, "{broken"])
    def test_unreadable_backup_raises_and_keeps_state(self, state: str | None) -> None:
        _plant(_OLD_ID, state=state, meta="{}")
        _write_state()
        with pytest.raises(backups.BackupError, match="unreadable"):
            backups.restore_backup(_OLD_ID)
        assert config.STATE_FILE.read_text(encoding="utf-8") == '{"current_app_id": 1}'

    def test_malformed_id_raises(self) -> None:
        with pytest.raises(backups.BackupError):
            backups.restore_backup("../../etc")
