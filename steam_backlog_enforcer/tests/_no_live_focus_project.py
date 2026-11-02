"""Autouse: no live focus project reshapes the earner registry in a test."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _no_live_focus_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point focus_project at an empty directory (earned_time >= 0.19)."""
    monkeypatch.setenv("FOCUS_PROJECT_DATA", str(tmp_path / "focus_project"))
