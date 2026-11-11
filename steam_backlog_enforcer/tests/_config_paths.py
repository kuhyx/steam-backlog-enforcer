"""Shared redirect of the config module's on-disk paths for the config tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def config_file_under(tmp_path: Path) -> Iterator[Path]:
    """Point CONFIG_DIR at ``tmp_path/cfg`` and yield its (unwritten) config.json."""
    config_dir = tmp_path / "cfg"
    config_file = config_dir / "config.json"
    with (
        patch("steam_backlog_enforcer.config.CONFIG_DIR", config_dir),
        patch("steam_backlog_enforcer.config.CONFIG_FILE", config_file),
    ):
        yield config_file
