"""install.sh --check-only: what a run needs, with steamcmd no longer on the list."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _stub(bin_dir: Path, name: str, script: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/bash\n{script}\n")
    path.chmod(0o755)


def _check_only(tmp_path, libibus_installed: bool):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "depotdownloader", "exit 0")
    _stub(bin_dir, "pacman", f'[[ "$*" == "-Q libibus" ]] && exit {0 if libibus_installed else 1}; exit 0')
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--check-only"],
        capture_output=True, text=True, env=env, timeout=30, check=False,
    )


def test_missing_libibus_is_reported_and_steamcmd_is_not_needed(tmp_path):
    result = _check_only(tmp_path, libibus_installed=False)
    assert result.returncode == 1
    assert "missing: libibus" in result.stderr
    assert "steamcmd" not in result.stdout + result.stderr


def test_all_present_without_steamcmd(tmp_path):
    result = _check_only(tmp_path, libibus_installed=True)
    assert result.returncode == 0, result.stderr
    assert "All dependencies present." in result.stdout


def test_run_sh_rechecks_when_the_proton_pin_changes():
    """A stale stamp must not hide a lock bump or a deleted tool folder."""
    text = (ROOT / "run.sh").read_text()
    assert "proton-native.lock" in text
    assert "steam_installer.proton_native --check" in text
