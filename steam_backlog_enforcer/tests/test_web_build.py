"""Tests for _web_build — 100% branch coverage.

Every module-level path constant is derived from the real repo ``web/`` at
import time, so each test redirects all of them into ``tmp_path``.  Patching
only ``WEB_DIR`` would leave ``_BUILT_MARKER`` and friends pointing at the
working tree, and the tests would silently grade the developer's own bundle.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _web_build

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._web_build"


@pytest.fixture
def web(tmp_path: Path) -> Iterator[Path]:
    """Redirect the whole module's path constants into a fake web/ tree."""
    root = tmp_path / "web"
    (root / "src").mkdir(parents=True)
    (root / "dist").mkdir()
    with (
        patch.object(_web_build, "WEB_DIR", root),
        patch.object(_web_build, "_BUILT_MARKER", root / "dist" / "index.html"),
        patch.object(_web_build, "_SOURCE_DIR", root / "src"),
        patch.object(
            _web_build,
            "_SOURCE_FILES",
            (root / "index.html", root / "package.json"),
        ),
    ):
        yield root


def _touch(path: Path, mtime: float) -> None:
    """Create *path* with a fixed mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    import os

    os.utime(path, (mtime, mtime))


class TestMtime:
    """Tests for the _mtime helper."""

    def test_missing_path_is_zero(self, tmp_path: Path) -> None:
        assert _web_build._mtime(tmp_path / "nope") == 0.0

    def test_existing_path_returns_mtime(self, tmp_path: Path) -> None:
        target = tmp_path / "f"
        _touch(target, 1000.0)
        assert _web_build._mtime(target) == pytest.approx(1000.0)


class TestFrontendIsStale:
    """Tests for frontend_is_stale."""

    def test_unbuilt_but_present_web_dir_is_stale(self, web: Path) -> None:
        # No dist/index.html at all: a fresh clone must build, not serve the
        # "not built" placeholder.
        assert web.is_dir()
        assert _web_build.frontend_is_stale() is True

    def test_missing_web_dir_is_not_stale(self, web: Path) -> None:
        # Nothing to build from — claiming staleness would make serve exit 1
        # on an install that legitimately ships no frontend sources.
        with patch.object(_web_build, "WEB_DIR", web / "absent"):
            assert _web_build.frontend_is_stale() is False

    def test_newer_source_file_is_stale(self, web: Path) -> None:
        _touch(web / "dist" / "index.html", 1000.0)
        _touch(web / "package.json", 2000.0)
        assert _web_build.frontend_is_stale() is True

    def test_newer_src_tree_entry_is_stale(self, web: Path) -> None:
        _touch(web / "dist" / "index.html", 1000.0)
        _touch(web / "src" / "nested" / "app.tsx", 2000.0)
        assert _web_build.frontend_is_stale() is True

    def test_all_sources_older_is_current(self, web: Path) -> None:
        _touch(web / "package.json", 1000.0)
        _touch(web / "src" / "app.tsx", 1000.0)
        _touch(web / "dist" / "index.html", 2000.0)
        assert _web_build.frontend_is_stale() is False

    def test_directories_in_src_are_skipped(self, web: Path) -> None:
        # A directory's own mtime bumps whenever a file inside it is added or
        # removed, so counting it would report staleness after a build.
        _touch(web / "src" / "old.tsx", 1000.0)
        _touch(web / "dist" / "index.html", 2000.0)
        (web / "src" / "assets").mkdir()
        assert _web_build.frontend_is_stale() is False

    def test_missing_src_dir_still_checks_flat_sources(self, web: Path) -> None:
        _touch(web / "dist" / "index.html", 1000.0)
        _touch(web / "index.html", 2000.0)
        with patch.object(_web_build, "_SOURCE_DIR", web / "absent"):
            assert _web_build.frontend_is_stale() is True


class TestBuildFrontend:
    """Tests for build_frontend. subprocess is never actually executed."""

    def test_missing_npm_explains_and_fails(self, web: Path) -> None:
        with (
            patch(f"{_PKG}.shutil.which", return_value=None),
            patch(f"{_PKG}._echo") as echo,
        ):
            assert _web_build.build_frontend() is False
        assert "npm was not found" in echo.call_args[0][0]

    def test_successful_build_returns_true(self, web: Path) -> None:
        run = MagicMock(return_value=MagicMock(returncode=0))
        with (
            patch(f"{_PKG}.shutil.which", return_value="/usr/bin/npm"),
            patch(f"{_PKG}.subprocess.run", run),
            patch(f"{_PKG}._echo"),
        ):
            assert _web_build.build_frontend() is True
        assert run.call_args[0][0] == ["/usr/bin/npm", "run", "build"]
        assert run.call_args[1]["cwd"] == web

    def test_failed_build_prints_output_and_returns_false(self, web: Path) -> None:
        result = MagicMock(returncode=1, stdout=" out \n", stderr=" err \n")
        with (
            patch(f"{_PKG}.shutil.which", return_value="/usr/bin/npm"),
            patch(f"{_PKG}.subprocess.run", return_value=result),
            patch(f"{_PKG}._echo") as echo,
        ):
            assert _web_build.build_frontend() is False
        printed = [call[0][0] for call in echo.call_args_list]
        assert any("FAILED" in line for line in printed)
        assert "out" in printed
        assert "err" in printed

    def test_timeout_propagates(self, web: Path) -> None:
        # A hung build must not be swallowed into "bundle is fine".
        with (
            patch(f"{_PKG}.shutil.which", return_value="/usr/bin/npm"),
            patch(
                f"{_PKG}.subprocess.run",
                side_effect=subprocess.TimeoutExpired("npm", 1),
            ),
            patch(f"{_PKG}._echo"),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            _web_build.build_frontend()
