"""scripts/deploy.sh against a fixture checkout instead of kuhy's real one."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh"

# Stubs stand in for the real run.sh / venv so the test installs nothing.
RUN_SH = '#!/bin/bash\n[[ "$1" == --deps-only ]] && touch .deps-ran\n'
VENV_PY = '#!/bin/bash\n[[ -f "$(dirname "$0")/healthy" ]]\n'


def _git(cwd: Path, *args: str) -> str:
    """Run git quietly in cwd and return stdout."""
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, body: str, mode: int = 0o644) -> None:
    """Write one file into repo and commit it."""
    path = repo / name
    path.write_text(body)
    path.chmod(mode)
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path]:
    """An origin with run.sh and a clone of it that is one commit behind."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _commit(origin, ".gitignore", ".venv/\n.deps-ran\n")
    _commit(origin, "run.sh", RUN_SH, 0o755)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    _commit(origin, "new.txt", "new\n")
    venv_bin = clone / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text(VENV_PY)
    (venv_bin / "python").chmod(0o755)
    (venv_bin / "healthy").touch()
    return origin, clone


def _deploy(clone: Path) -> subprocess.CompletedProcess[str]:
    """Run deploy.sh pointed at the fixture clone."""
    env = {**os.environ, "SGI_DEPLOY_DIR": str(clone)}
    return subprocess.run(
        ["bash", str(DEPLOY)], env=env, capture_output=True, text=True, check=False
    )


def test_deploy_fast_forwards_installs_and_checks(
    checkout: tuple[Path, Path],
) -> None:
    """A clean checkout ends at origin/main with deps run and exit 0."""
    origin, clone = checkout
    result = _deploy(clone)
    assert result.returncode == 0, result.stderr
    assert _git(clone, "rev-parse", "HEAD") == _git(origin, "rev-parse", "HEAD")
    assert (clone / ".deps-ran").exists()
    assert _deploy(clone).returncode == 0  # idempotent


def test_deploy_refuses_dirty_checkout(checkout: tuple[Path, Path]) -> None:
    """Local edits in kuhy's checkout are never overwritten."""
    _, clone = checkout
    (clone / "run.sh").write_text(RUN_SH + "# local edit\n")
    result = _deploy(clone)
    assert result.returncode != 0
    assert "local changes" in result.stderr


def test_deploy_fails_when_health_check_fails(checkout: tuple[Path, Path]) -> None:
    """A CLI that cannot start makes deploy exit non-zero."""
    _, clone = checkout
    (clone / ".venv" / "bin" / "healthy").unlink()
    result = _deploy(clone)
    assert result.returncode != 0
    assert "health" in result.stderr


def test_claude_md_declares_deploy() -> None:
    """CLAUDE.md names scripts/deploy.sh as the deploy command."""
    claude = DEPLOY.parent.parent / "CLAUDE.md"
    assert "- deploy: `scripts/deploy.sh`" in claude.read_text()
