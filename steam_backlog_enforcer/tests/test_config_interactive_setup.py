"""Tests for config module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._config_setup import interactive_setup

if TYPE_CHECKING:
    from pathlib import Path


class TestInteractiveSetup:
    """Tests for interactive_setup."""

    def test_success(self, tmp_path: Path) -> None:
        """Test success."""
        config_dir = tmp_path / "cfg"
        config_file = config_dir / "config.json"
        with (
            patch("steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("steam_backlog_enforcer.config.CONFIG_FILE", config_file),
            patch("builtins.input", side_effect=["mykey", "myid"]),
        ):
            cfg = interactive_setup()
            assert cfg.steam_api_key == "mykey"
            assert cfg.steam_id == "myid"
            assert config_file.exists()

    def test_empty_api_key_exits(self) -> None:
        """Test empty api key exits."""
        with (
            patch("builtins.input", return_value=""),
            pytest.raises(SystemExit),
        ):
            interactive_setup()

    def test_empty_steam_id_exits(self, tmp_path: Path) -> None:
        """Test empty steam id exits."""
        config_dir = tmp_path / "cfg"
        config_file = config_dir / "config.json"
        with (
            patch("steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
            patch("steam_backlog_enforcer.config.CONFIG_FILE", config_file),
            patch("builtins.input", side_effect=["key", ""]),
            pytest.raises(SystemExit),
        ):
            interactive_setup()
