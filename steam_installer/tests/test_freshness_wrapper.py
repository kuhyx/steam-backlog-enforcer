"""The freshness wrapper fails closed when ~/src/utils cannot read the Proton lock."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

WRAPPER = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_dependency_freshness.sh"
)
LOCK = "steam_installer/data/proton-native.lock"


BASH = shutil.which("bash") or "bash"
GIT = shutil.which("git") or "git"


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
        [BASH, str(WRAPPER), *args],
        env={"UTILS_ROOT": str(root), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_lock_without_the_pacman_adapter_fails(tmp_path: Path) -> None:
    """Lock without the pacman adapter fails."""
    result = _run(_utils(tmp_path, adapter=False), LOCK)
    assert result.returncode == 1
    assert "pacman_lock" in result.stderr
    assert "shared-gate-ran" not in result.stdout


def test_full_run_without_the_pacman_adapter_fails(tmp_path: Path) -> None:
    """Full run without the pacman adapter fails."""
    assert _run(_utils(tmp_path, adapter=False), "--all", "--strict").returncode == 1


def test_lock_with_the_adapter_reaches_the_shared_gate(tmp_path: Path) -> None:
    """Lock with the adapter reaches the shared gate."""
    result = _run(_utils(tmp_path, adapter=True), LOCK)
    assert result.returncode == 0
    assert "shared-gate-ran" in result.stdout


def test_other_manifests_skip_the_adapter_check(tmp_path: Path) -> None:
    """Other manifests skip the adapter check."""
    result = _run(_utils(tmp_path, adapter=False), "requirements.txt")
    assert result.returncode == 0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _diverged_utils(tmp_path: Path, *, origin_has_adapter: bool) -> Path:
    """A utils checkout without the adapter whose origin/main may have it."""
    root = _utils(tmp_path, adapter=False)
    _git(root, "init", "-q")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "old")
    old = _git(root, "rev-parse", "HEAD")
    if origin_has_adapter:
        gate = root / "scripts" / "check_dependency_freshness.sh"
        gate.write_text('#!/bin/bash\necho "snapshot-gate-ran $(dirname "$0")"\n')
        parser = root / "dep_freshness" / "parsers" / "pacman_lock.py"
        parser.parent.mkdir(parents=True)
        parser.write_text("")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "new")
    _git(
        root, "update-ref", "refs/remotes/origin/main", _git(root, "rev-parse", "HEAD")
    )
    _git(root, "reset", "-q", "--hard", old)
    return root


def _run_cached(root: Path, cache: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(WRAPPER), *args],
        env={
            "UTILS_ROOT": str(root),
            "PATH": "/usr/bin:/bin",
            "XDG_CACHE_HOME": str(cache),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_old_checkout_runs_origin_main_snapshot(tmp_path: Path) -> None:
    """Old checkout runs origin main snapshot."""
    root = _diverged_utils(tmp_path, origin_has_adapter=True)
    result = _run_cached(root, tmp_path / "cache", LOCK)
    assert result.returncode == 0, result.stderr
    assert "snapshot-gate-ran" in result.stdout
    assert str(tmp_path / "cache") in result.stdout
    # The checkout itself is left exactly as it was.
    assert not (root / "dep_freshness" / "parsers" / "pacman_lock.py").exists()


def test_old_checkout_and_old_origin_fail_closed(tmp_path: Path) -> None:
    """Old checkout and old origin fail closed."""
    root = _diverged_utils(tmp_path, origin_has_adapter=False)
    result = _run_cached(root, tmp_path / "cache", LOCK)
    assert result.returncode == 1
    assert "pacman_lock" in result.stderr
