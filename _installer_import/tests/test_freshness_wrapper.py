"""The freshness wrapper fails closed when ~/src/utils cannot read the Proton lock."""

import subprocess
from pathlib import Path

WRAPPER = Path(__file__).resolve().parent.parent / "scripts" / "check_dependency_freshness.sh"
LOCK = "steam_installer/data/proton-native.lock"


def _utils(tmp_path: Path, *, adapter: bool) -> Path:
    root = tmp_path / "utils"
    gate = root / "scripts" / "check_dependency_freshness.sh"
    gate.parent.mkdir(parents=True)
    gate.write_text("#!/bin/bash\necho shared-gate-ran\n")
    gate.chmod(0o755)
    if adapter:
        parser = root / "dep_freshness" / "parsers" / "pacman_lock.py"
        parser.parent.mkdir(parents=True)
        parser.write_text("")
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(WRAPPER), *args],
        env={"UTILS_ROOT": str(root), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_lock_without_the_pacman_adapter_fails(tmp_path):
    result = _run(_utils(tmp_path, adapter=False), LOCK)
    assert result.returncode == 1
    assert "pacman_lock" in result.stderr
    assert "shared-gate-ran" not in result.stdout


def test_full_run_without_the_pacman_adapter_fails(tmp_path):
    assert _run(_utils(tmp_path, adapter=False), "--all", "--strict").returncode == 1


def test_lock_with_the_adapter_reaches_the_shared_gate(tmp_path):
    result = _run(_utils(tmp_path, adapter=True), LOCK)
    assert result.returncode == 0
    assert "shared-gate-ran" in result.stdout


def test_other_manifests_skip_the_adapter_check(tmp_path):
    result = _run(_utils(tmp_path, adapter=False), "requirements.txt")
    assert result.returncode == 0
