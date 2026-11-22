"""The proton_native entry point: what install_deps.sh and run.sh call."""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING, Never

from steam_installer import proton_native, proton_pkg
from steam_installer.proton_native import _download
from steam_installer.tests._run_helpers import run_captured

if TYPE_CHECKING:
    from pathlib import Path
    from urllib.request import Request

    import pytest


def _boom(*_a: object, **_kw: object) -> Never:
    msg = "bad signature"
    raise proton_pkg.PkgError(msg)


def test_main_exits_zero_on_success_and_one_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Main exits zero on success and one on failure."""
    monkeypatch.setattr(proton_native, "ensure", lambda *a, **kw: "current: x")
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    assert proton_native.main([]) == 0
    monkeypatch.setattr(proton_native, "ensure", _boom)
    assert proton_native.main([]) == 1


def test_main_reports_what_happened(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Main reports what happened."""
    monkeypatch.setattr(proton_native, "ensure", lambda *a, **kw: "current: x")
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    assert proton_native.main([]) == 0
    assert "current: x" in capsys.readouterr().out
    monkeypatch.setattr(proton_native, "ensure", _boom)
    assert proton_native.main([]) == 1
    assert "bad signature" in capsys.readouterr().err


def test_check_reports_whether_the_stamp_matches_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check reports whether the stamp matches the lock."""
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    assert proton_native.main(["--check"]) == 1
    tool = tmp_path / "compatibilitytools.d" / "proton-cachyos-native"
    tool.mkdir(parents=True)
    (tool / "VERSION").write_text(proton_pkg.read_lock().version + "\n")
    assert proton_native.main(["--check"]) == 0


def _absent() -> Never:
    msg = "No Steam installation found"
    raise FileNotFoundError(msg)


def test_no_steam_installation_means_nothing_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No steam installation means nothing to install."""
    monkeypatch.setattr(proton_native, "find_steam_root", _absent)
    assert proton_native.main([]) == 0
    assert proton_native.main(["--check"]) == 0


def test_no_steam_installation_says_it_was_skipped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No steam installation says it was skipped."""
    monkeypatch.setattr(proton_native, "find_steam_root", _absent)
    assert proton_native.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_the_repo_can_be_pointed_at_a_test_mirror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The repo can be pointed at a test mirror."""
    seen = {}
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    monkeypatch.setenv("SGI_PROTON_REPO", "file:///mirror/cachyos.db")
    monkeypatch.setattr(
        proton_native, "ensure", lambda d, lock: seen.setdefault("repo", lock.repo)
    )
    assert proton_native.main([]) == 0
    assert seen["repo"] == "file:///mirror/cachyos.db"


def test_module_runs_as_a_script(
    tmp_path: Path, coverage_subprocess_env: dict[str, str]
) -> None:
    """Module runs as a script."""
    env = {**coverage_subprocess_env, "HOME": str(tmp_path)}
    result = run_captured(
        [sys.executable, "-m", "steam_installer.proton_native", "--check"], env
    )
    assert result.returncode == 0
    assert "skipped" in result.stdout


def test_downloads_send_a_user_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CachyOS mirror answers 403 to urllib's default agent (2026-11-22)."""
    seen = {}

    class _Response(io.BytesIO):
        """A urlopen response: BytesIO already works as a context manager."""

    def fake_urlopen(request: Request, **_kw: float) -> _Response:
        seen["agent"] = request.get_header("User-agent")
        return _Response(b"data")

    monkeypatch.setattr(proton_native.urllib.request, "urlopen", fake_urlopen)
    _download("https://m/x", tmp_path / "x")
    assert (tmp_path / "x").read_bytes() == b"data"
    assert seen["agent"] == "steam-game-installer"


def test_a_file_url_is_a_plain_copy(tmp_path: Path) -> None:
    """A file:// mirror (SGI_PROTON_REPO) is read straight from disk."""
    source = tmp_path / "a b.db"
    source.write_bytes(b"db")
    _download(source.as_uri(), tmp_path / "out")
    assert (tmp_path / "out").read_bytes() == b"db"
