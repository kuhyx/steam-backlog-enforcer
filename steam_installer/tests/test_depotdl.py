"""Tests for depotdl."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from steam_installer import depotdl

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Intercept the subprocess call and hand back the argv it was given."""
    seen = {}

    def fake_run_logged(
        cmd: list[str], _logger: logging.Logger, **_kw: float | None
    ) -> tuple[int, str]:
        seen["cmd"] = cmd
        return seen.get("rc", 0), ""

    monkeypatch.setattr(depotdl.runlog, "run_logged", fake_run_logged)
    return seen


def test_download_builds_expected_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Download builds expected argv."""
    seen = _capture(monkeypatch)

    pull = depotdl.Pull(tmp_path / "Game", "krzys2000", "english", 32)
    depotdl.download(1771300, pull, logging.getLogger("t"))

    cmd = seen["cmd"]
    assert cmd[0] == "depotdownloader"
    pairs = dict(zip(cmd[1::2], cmd[2::2], strict=False))
    assert pairs["-app"] == "1771300"
    assert pairs["-language"] == "english"
    assert pairs["-max-downloads"] == "32"
    assert pairs["-username"] == "krzys2000"


def test_download_always_passes_os_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without -os, depotdownloader defaults to the host OS and can filter out
    every real (Windows-tagged) depot -- the original "0 bytes from 0 depots"."""
    seen = _capture(monkeypatch)

    depotdl.download(
        1771300, depotdl.Pull(tmp_path / "Game", "u"), logging.getLogger("t")
    )

    cmd = seen["cmd"]
    assert cmd[cmd.index("-os") + 1] == "windows"
    assert "-remember-password" in cmd


def test_download_creates_the_install_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Download creates the install dir."""
    _capture(monkeypatch)
    target = tmp_path / "nested" / "Game"

    depotdl.download(1, depotdl.Pull(target, "u"), logging.getLogger("t"))

    assert target.is_dir()


def test_download_returns_the_exit_code_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller must distinguish "download failed" from "manifest step failed"
    to decide whether touching the manifest is safe at all."""
    seen = _capture(monkeypatch)
    seen["rc"] = 1

    returncode = depotdl.download(
        1, depotdl.Pull(tmp_path / "Game", "u"), logging.getLogger("t")
    )

    assert returncode == 1
