"""Tests for config module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from python_pkg.steam_backlog_enforcer.config import (
    Config,
    State,
    _atomic_write,
    interactive_setup,
    load_snapshot,
    save_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestAtomicWrite:
    """Tests for _atomic_write."""

    def test_writes_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        _atomic_write(target, '{"key": "value"}\n')
        assert target.read_text(encoding="utf-8") == '{"key": "value"}\n'

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "deep" / "out.json"
        _atomic_write(target, "data")
        assert target.read_text(encoding="utf-8") == "data"

    def test_cleanup_on_write_error(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.config.os.write",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError, match="disk full"),
        ):
            _atomic_write(target, "data")
        assert not target.exists()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_cleanup_on_replace_error(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        with (
            patch.object(
                type(target),
                "replace",
                side_effect=OSError("no perm"),
            ),
            pytest.raises(OSError, match="no perm"),
        ):
            _atomic_write(target, "data")
        assert not target.exists()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


class TestConfig:
    """Tests for Config dataclass."""

    def test_defaults(self) -> None:
        cfg = Config()
        assert cfg.steam_api_key == ""
        assert cfg.steam_id == ""
        assert cfg.skip_app_ids == []
        assert cfg.block_store is True
        assert cfg.kill_unauthorized_games is True
        assert cfg.uninstall_other_games is True
        assert cfg.desktop_notifications is True

    def test_save(self, tmp_path: Path) -> None:
        cfg = Config(steam_api_key="abc", steam_id="123")
        config_dir = tmp_path / "cfg"
        config_file = config_dir / "config.json"
        with (
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_FILE", config_file),
        ):
            cfg.save()
            data = json.loads(config_file.read_text(encoding="utf-8"))
            assert data["steam_api_key"] == "abc"
            assert data["steam_id"] == "123"

    def test_load_existing(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"steam_api_key": "key1", "steam_id": "id1"}) + "\n",
            encoding="utf-8",
        )
        with patch("python_pkg.steam_backlog_enforcer.config.CONFIG_FILE", config_file):
            cfg = Config.load()
            assert cfg.steam_api_key == "key1"
            assert cfg.steam_id == "id1"

    def test_load_missing(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nonexistent.json"
        with patch("python_pkg.steam_backlog_enforcer.config.CONFIG_FILE", config_file):
            cfg = Config.load()
            assert cfg.steam_api_key == ""

    def test_load_extra_fields_ignored(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"steam_api_key": "k", "unknown_field": 42}) + "\n",
            encoding="utf-8",
        )
        with patch("python_pkg.steam_backlog_enforcer.config.CONFIG_FILE", config_file):
            cfg = Config.load()
            assert cfg.steam_api_key == "k"


class TestState:
    """Tests for State dataclass."""

    def test_defaults(self) -> None:
        state = State()
        assert state.current_app_id is None
        assert state.current_game_name == ""
        assert state.finished_app_ids == []

    def test_save(self, tmp_path: Path) -> None:
        state = State(current_app_id=100, current_game_name="TestGame")
        config_dir = tmp_path / "cfg"
        state_file = config_dir / "state.json"
        with (
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("python_pkg.steam_backlog_enforcer.config.STATE_FILE", state_file),
        ):
            state.save()
            data = json.loads(state_file.read_text(encoding="utf-8"))
            assert data["current_app_id"] == 100
            assert data["current_game_name"] == "TestGame"

    def test_load_existing(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "current_app_id": 50,
                    "current_game_name": "G",
                    "finished_app_ids": [1, 2],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with patch("python_pkg.steam_backlog_enforcer.config.STATE_FILE", state_file):
            st = State.load()
            assert st.current_app_id == 50
            assert st.finished_app_ids == [1, 2]

    def test_load_missing(self, tmp_path: Path) -> None:
        state_file = tmp_path / "nonexistent.json"
        with patch("python_pkg.steam_backlog_enforcer.config.STATE_FILE", state_file):
            st = State.load()
            assert st.current_app_id is None

    def test_load_corrupt(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json{{", encoding="utf-8")
        with patch("python_pkg.steam_backlog_enforcer.config.STATE_FILE", state_file):
            st = State.load()
            assert st.current_app_id is None
            assert st.current_game_name == ""


class TestSnapshot:
    """Tests for snapshot save/load."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        snap_file = config_dir / "snapshot.json"
        with (
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("python_pkg.steam_backlog_enforcer.config.SNAPSHOT_FILE", snap_file),
        ):
            data: list[dict[str, Any]] = [{"app_id": 1, "name": "G1"}]
            save_snapshot(data)
            loaded = load_snapshot()
            assert loaded == data

    def test_load_none(self, tmp_path: Path) -> None:
        snap_file = tmp_path / "nonexistent.json"
        with patch("python_pkg.steam_backlog_enforcer.config.SNAPSHOT_FILE", snap_file):
            assert load_snapshot() is None


class TestInteractiveSetup:
    """Tests for interactive_setup."""

    def test_success(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        config_file = config_dir / "config.json"
        with (
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_FILE", config_file),
            patch("builtins.input", side_effect=["mykey", "myid"]),
        ):
            cfg = interactive_setup()
            assert cfg.steam_api_key == "mykey"
            assert cfg.steam_id == "myid"
            assert config_file.exists()

    def test_empty_api_key_exits(self) -> None:
        with (
            patch("builtins.input", return_value=""),
            pytest.raises(SystemExit),
        ):
            interactive_setup()

    def test_empty_steam_id_exits(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        config_file = config_dir / "config.json"
        with (
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("python_pkg.steam_backlog_enforcer.config.CONFIG_FILE", config_file),
            patch("builtins.input", side_effect=["key", ""]),
            pytest.raises(SystemExit),
        ):
            interactive_setup()
