"""install_deps.sh --check-only: what a run needs; steamcmd is gone from it."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from steam_installer.tests._run_helpers import run_captured

if TYPE_CHECKING:
    import subprocess

PKG = Path(__file__).resolve().parents[1]


BASH = shutil.which("bash") or "bash"


def _stub(bin_dir: Path, name: str, script: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/bash\n{script}\n")
    path.chmod(0o755)


def _check_only(
    tmp_path: Path, *, libibus_installed: bool, proton_ok: bool = True
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "depotdownloader", "exit 0")
    _stub(
        bin_dir,
        "pacman",
        f'[[ "$*" == "-Q libibus" ]] && exit {0 if libibus_installed else 1}; exit 0',
    )
    # The real `--check` would look at the developer's own Steam tree.
    _stub(bin_dir, "python3", f"exit {0 if proton_ok else 1}")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SGI_PYTHON": str(bin_dir / "python3"),
    }
    return run_captured([BASH, str(PKG / "install_deps.sh"), "--check-only"], env)


def test_missing_libibus_is_reported_and_steamcmd_is_not_needed(tmp_path: Path) -> None:
    """Missing libibus is reported and steamcmd is not needed."""
    result = _check_only(tmp_path, libibus_installed=False)
    assert result.returncode == 1
    assert "missing: libibus" in result.stderr
    assert "steamcmd" not in result.stdout + result.stderr


def test_all_present_without_steamcmd(tmp_path: Path) -> None:
    """All present without steamcmd."""
    result = _check_only(tmp_path, libibus_installed=True)
    assert result.returncode == 0, result.stderr
    assert "All dependencies present." in result.stdout


def test_run_sh_rechecks_when_the_proton_pin_changes() -> None:
    """A stale stamp must not hide a lock bump or a deleted tool folder."""
    text = (PKG / "run.sh").read_text()
    assert "proton-native.lock" in text
    assert "steam_installer.proton_native --check" in text


def test_missing_native_proton_is_reported(tmp_path: Path) -> None:
    """Missing native proton is reported."""
    result = _check_only(tmp_path, libibus_installed=True, proton_ok=False)
    assert result.returncode == 1
    assert "missing: proton-cachyos-native" in result.stderr
