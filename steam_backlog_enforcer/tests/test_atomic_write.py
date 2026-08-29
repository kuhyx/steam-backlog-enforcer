"""Tests for _atomic_write — the shared atomic file-write primitive.

Split out of ``test_config.py`` to hold both files inside the 250-line cap;
``_atomic_write`` is a file-writing primitive rather than part of the config
data model, and its permission behaviour is what several other modules rely on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import _atomic_write

if TYPE_CHECKING:
    from pathlib import Path


class TestAtomicWrite:
    """Tests for _atomic_write."""

    def test_writes_file(self, tmp_path: Path) -> None:
        """Test writes file."""
        target = tmp_path / "out.json"
        _atomic_write(target, '{"key": "value"}\n')
        assert target.read_text(encoding="utf-8") == '{"key": "value"}\n'

    def test_defaults_to_owner_only(self, tmp_path: Path) -> None:
        """Files that may hold secrets keep mkstemp's 0600."""
        target = tmp_path / "out.json"
        _atomic_write(target, "data")
        assert target.stat().st_mode & 0o777 == 0o600

    def test_honours_an_explicit_mode(self, tmp_path: Path) -> None:
        """The mode lands on the result, not just on the temp file."""
        target = tmp_path / "out.json"
        _atomic_write(target, "data", mode=0o644)
        assert target.stat().st_mode & 0o777 == 0o644

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Test creates parent dirs."""
        target = tmp_path / "sub" / "deep" / "out.json"
        _atomic_write(target, "data")
        assert target.read_text(encoding="utf-8") == "data"

    def test_cleanup_on_write_error(self, tmp_path: Path) -> None:
        """Test cleanup on write error."""
        target = tmp_path / "out.json"
        with (
            patch(
                "steam_backlog_enforcer.config.os.write",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError, match="disk full"),
        ):
            _atomic_write(target, "data")
        assert not target.exists()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_cleanup_on_replace_error(self, tmp_path: Path) -> None:
        """Test cleanup on replace error."""
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
