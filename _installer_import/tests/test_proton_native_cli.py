"""The proton_native entry point: what install.sh and run.sh call."""

import subprocess
import sys

from steam_installer import proton_native, proton_pkg


def test_main_reports_and_exits(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(proton_native, "ensure", lambda *a, **kw: "current: x")
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    assert proton_native.main([]) == 0
    assert "current: x" in capsys.readouterr().out

    def boom(*a, **kw):
        raise proton_pkg.PkgError("bad signature")

    monkeypatch.setattr(proton_native, "ensure", boom)
    assert proton_native.main([]) == 1
    assert "bad signature" in capsys.readouterr().err


def test_check_reports_whether_the_stamp_matches_the_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    assert proton_native.main(["--check"]) == 1
    tool = tmp_path / "compatibilitytools.d" / "proton-cachyos-native"
    tool.mkdir(parents=True)
    (tool / "VERSION").write_text(proton_pkg.read_lock().version + "\n")
    assert proton_native.main(["--check"]) == 0


def test_no_steam_installation_means_nothing_to_install(monkeypatch, capsys):
    def absent():
        raise FileNotFoundError("No Steam installation found")

    monkeypatch.setattr(proton_native, "find_steam_root", absent)
    assert proton_native.main([]) == 0
    assert proton_native.main(["--check"]) == 0
    assert "skipped" in capsys.readouterr().out


def test_the_repo_can_be_pointed_at_a_test_mirror(monkeypatch, tmp_path, capsys):
    seen = {}
    monkeypatch.setattr(proton_native, "find_steam_root", lambda: tmp_path)
    monkeypatch.setenv("SGI_PROTON_REPO", "file:///mirror/cachyos.db")
    monkeypatch.setattr(proton_native, "ensure", lambda d, lock: seen.setdefault("repo", lock.repo))
    assert proton_native.main([]) == 0
    assert seen["repo"] == "file:///mirror/cachyos.db"


def test_module_runs_as_a_script(tmp_path, coverage_subprocess_env):
    env = {**coverage_subprocess_env, "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "steam_installer.proton_native", "--check"],
        capture_output=True, text=True, env=env, timeout=30, check=False,
    )
    assert result.returncode == 0
    assert "skipped" in result.stdout


def test_downloads_send_a_user_agent(monkeypatch, tmp_path):
    """The CachyOS mirror answers 403 to urllib's default agent (2026-11-22)."""
    import io

    seen = {}

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout):
        seen["agent"] = request.get_header("User-agent")
        return _Response(b"data")

    monkeypatch.setattr(proton_native.urllib.request, "urlopen", fake_urlopen)
    proton_native._download("https://m/x", tmp_path / "x")
    assert (tmp_path / "x").read_bytes() == b"data"
    assert seen["agent"] == "steam-game-installer"
