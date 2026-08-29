"""Tests for _serve_stale: a server must not outlive its own source.

On 2026-08-29 a hand-started ``python -c`` server stayed up for hours after the
code beneath it changed, reporting an 8h gaming budget while the daemon
enforced 6h. The launcher guard could not have helped: it only runs from
``cmd_serve``, which that process never went through. So the check lives in the
server, where no launch path can skip it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._serve_stale import (
    _RECHECK_INTERVAL_SECONDS,
    outdated_source,
    reset_cache,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._serve_stale"


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    """Keep the memo from leaking answers between tests.

    Yields:
        None, with the cache empty before and after.
    """
    reset_cache()
    yield
    reset_cache()


@pytest.fixture
def fake_package(tmp_path: Path) -> Path:
    """Point the module at a throwaway package tree.

    Args:
        tmp_path: pytest temporary directory.

    Returns:
        The fake package root.
    """
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "module.py").write_text("x = 1\n", encoding="utf-8")
    return root


def _touch(path: Path, mtime: float) -> None:
    """Set a file's mtime.

    Args:
        path: File to stamp.
        mtime: Epoch seconds to set.
    """
    path.write_text("x = 2\n", encoding="utf-8")
    import os

    os.utime(path, (mtime, mtime))


class TestOutdatedSource:
    """The check answers "has my own code moved on since I started"."""

    def test_current_code_is_not_stale(self, fake_package: Path) -> None:
        """A tree older than the process start is fine."""
        _touch(fake_package / "module.py", 1000.0)
        with patch(f"{_PKG}._PACKAGE_ROOT", fake_package):
            assert outdated_source(2000.0, now=0.0) is None

    def test_a_newer_file_is_named(self, fake_package: Path) -> None:
        """The offending path is returned, so the refusal is auditable."""
        changed = fake_package / "module.py"
        _touch(changed, 3000.0)
        with patch(f"{_PKG}._PACKAGE_ROOT", fake_package):
            assert outdated_source(2000.0, now=0.0) == changed

    def test_staleness_is_logged_at_error(
        self,
        fake_package: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Refusing to serve is loud: it needs to reach the journal."""
        _touch(fake_package / "module.py", 3000.0)
        with (
            caplog.at_level(logging.ERROR),
            patch(f"{_PKG}._PACKAGE_ROOT", fake_package),
        ):
            outdated_source(2000.0, now=0.0)
        assert "outdated code" in caplog.text
        assert "run.sh serve" in caplog.text

    def test_a_file_removed_mid_scan_is_skipped(self, fake_package: Path) -> None:
        """A vanished file cannot make the process stale."""
        _touch(fake_package / "module.py", 3000.0)
        with (
            patch(f"{_PKG}._PACKAGE_ROOT", fake_package),
            patch(
                "steam_backlog_enforcer._serve_stale.Path.stat",
                side_effect=OSError("gone"),
            ),
        ):
            assert outdated_source(2000.0, now=0.0) is None

    def test_the_answer_is_memoised(self, fake_package: Path) -> None:
        """Statting the whole package on every request would be wasteful."""
        _touch(fake_package / "module.py", 1000.0)
        with patch(f"{_PKG}._PACKAGE_ROOT", fake_package) as root:
            outdated_source(2000.0, now=0.0)
            # A change inside the memo window is deliberately not seen yet.
            _touch(root / "module.py", 3000.0)
            assert outdated_source(2000.0, now=1.0) is None

    def test_the_memo_expires(self, fake_package: Path) -> None:
        """The staleness window is bounded, unlike the staleness it replaces."""
        _touch(fake_package / "module.py", 1000.0)
        with patch(f"{_PKG}._PACKAGE_ROOT", fake_package) as root:
            outdated_source(2000.0, now=0.0)
            _touch(root / "module.py", 3000.0)
            later = _RECHECK_INTERVAL_SECONDS + 1
            assert outdated_source(2000.0, now=later) is not None

    def test_it_reads_the_clock_when_not_told_one(self, fake_package: Path) -> None:
        """The production path takes no `now`; exercise that branch too."""
        _touch(fake_package / "module.py", 1000.0)
        with patch(f"{_PKG}._PACKAGE_ROOT", fake_package):
            assert outdated_source(2000.0) is None
