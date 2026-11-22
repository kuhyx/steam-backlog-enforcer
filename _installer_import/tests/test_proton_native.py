"""Fetch, verify and install the native Proton, never running its .INSTALL."""

import os
import shutil

import pytest
from _proton_fixture import (
    FILES,
    VERSION,
    build_db,
    build_package,
    build_repo,
    gpg,
    stop_agent,
)

from steam_installer import proton_native, proton_pkg


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    built = build_repo(tmp_path_factory.mktemp("repo"))
    yield built
    stop_agent(built.gpg_home)


@pytest.fixture
def mirror(repo, tmp_path):
    """A private copy of the fake mirror a test may tamper with."""
    root = tmp_path / "mirror"
    shutil.copytree(repo.root, root)
    return root


@pytest.fixture
def setup(repo, mirror, tmp_path, monkeypatch):
    tools = tmp_path / "compatibilitytools.d"
    tools.mkdir()
    lock = proton_pkg.Lock(
        "proton-cachyos-native", (mirror / "cachyos.db").as_uri(), VERSION, repo.sha256
    )
    monkeypatch.setattr(proton_native, "in_use", lambda tool: [])

    def run(**kw):
        return proton_native.ensure(
            tools, lock, key=repo.key, fingerprint=repo.fingerprint, **kw
        )

    return tools, lock, run


def _tree(tool):
    return sorted(str(p.relative_to(tool)) for p in tool.rglob("*"))


def test_a_fresh_install_extracts_only_the_tool_and_stamps_it(setup):
    tools, _, run = setup
    status = run()
    tool = tools / "proton-cachyos-native"
    assert status.startswith("installed")
    assert "signature" in status and "sha256" in status
    assert (tool / "VERSION").read_text() == VERSION + "\n"
    assert (tool / "files/bin/wine").read_bytes() == FILES["files/bin/wine"]
    assert os.readlink(tool / "files/bin/msidb") == "wine"
    assert not (tools / ".INSTALL").exists()
    assert not any(".INSTALL" in p or "stray" in p for p in _tree(tools))
    assert sorted(os.listdir(tools)) == ["proton-cachyos-native"]


def test_a_current_stamp_needs_no_network(setup, monkeypatch):
    _, _, run = setup
    run()
    monkeypatch.setattr(proton_native, "_download", lambda url, dest: pytest.fail())
    assert run() == f"current: {VERSION}"


def _assert_fails_untouched(run, tools, match):
    old = tools / "proton-cachyos-native"
    old.mkdir(exist_ok=True)
    (old / "keep").write_text("old build")
    with pytest.raises(proton_pkg.PkgError, match=match):
        run()
    assert (old / "keep").read_text() == "old build"
    assert sorted(os.listdir(tools)) == ["proton-cachyos-native"]


def test_a_tampered_signature_fails_closed(setup, mirror):
    tools, _, run = setup
    sig = next(mirror.glob("*.sig"))
    data = bytearray(sig.read_bytes())
    data[-5] ^= 0xFF
    sig.write_bytes(bytes(data))
    _assert_fails_untouched(run, tools, "signature")


def test_a_signature_from_another_key_fails_closed(setup, mirror, tmp_path):
    tools, _, run = setup
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    gpg(other, "--quick-gen-key", "Mallory <m@example.invalid>", "ed25519", "sign", "never")
    package = next(mirror.glob("*.pkg.tar.zst"))
    (mirror / f"{package.name}.sig").unlink()
    gpg(other, "--output", f"{package}.sig", "--detach-sign", str(package))
    stop_agent(other)
    _assert_fails_untouched(run, tools, "signature")


def test_a_package_that_differs_from_the_pinned_sha256_fails_closed(setup, mirror, repo):
    tools, _, run = setup
    package = next(mirror.glob("*.pkg.tar.zst"))
    build_package(package, {**FILES, "proton": b"evil"})
    gpg(repo.gpg_home, "--yes", "--output", f"{package}.sig", "--detach-sign", str(package))
    _assert_fails_untouched(run, tools, "sha256")


def test_a_db_sha256_that_disagrees_with_the_lock_fails_closed(setup, mirror):
    tools, _, run = setup
    build_db(mirror / "cachyos.db", VERSION, "0" * 64)
    _assert_fails_untouched(run, tools, "sha256")


def test_a_newer_package_in_the_repo_asks_for_a_lock_bump(setup, mirror, repo):
    tools, _, run = setup
    build_db(mirror / "cachyos.db", "1:11.0.20261101-1", repo.sha256)
    _assert_fails_untouched(run, tools, "bump")


def test_a_repo_without_the_package_fails(setup, mirror, repo):
    tools, _, run = setup
    build_db(mirror / "cachyos.db", VERSION, repo.sha256, name="something-else")
    _assert_fails_untouched(run, tools, "no proton-cachyos-native")


def _existing_copy(tools):
    tool = tools / "proton-cachyos-native"
    for name, data in FILES.items():
        (tool / name).parent.mkdir(parents=True, exist_ok=True)
        (tool / name).write_bytes(data)
    os.symlink("wine", tool / "files/bin/msidb")
    (tool / "__pycache__").mkdir()
    (tool / "__pycache__" / "x.pyc").write_bytes(b"made by running it")
    return tool


def test_an_identical_copy_is_adopted_without_extracting(setup, monkeypatch):
    tools, _, run = setup
    tool = _existing_copy(tools)
    monkeypatch.setattr(proton_pkg, "extract", lambda *a: pytest.fail("extracted"))
    status = run()
    assert status.startswith(f"adopted: all {len(FILES) + 1} files match .MTREE (signature")
    assert (tool / "VERSION").read_text() == VERSION + "\n"


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda t: (t / "files/bin/wine").write_bytes(b"patched"), "files/bin/wine"),
        (lambda t: (t / "user_settings.py").write_text("x"), "user_settings.py"),
        (lambda t: (t / "proton").unlink(), "proton"),
        (lambda t: (t / "files/bin/msidb").unlink() or os.symlink("x", t / "files/bin/msidb"), "msidb"),
        (lambda t: (t / "files/bin/msidb").unlink(), "msidb"),
    ],
)
def test_a_differing_copy_is_replaced(setup, change, where):
    tools, _, run = setup
    tool = _existing_copy(tools)
    change(tool)
    status = run()
    assert status.startswith("replaced: mismatch in") and where in status
    assert (tool / "files/bin/wine").read_bytes() == FILES["files/bin/wine"]
    assert not (tool / "user_settings.py").exists()
    assert sorted(os.listdir(tools)) == ["proton-cachyos-native"]


def test_replacing_is_deferred_while_steam_or_a_game_runs(setup, monkeypatch):
    tools, _, run = setup
    tool = _existing_copy(tools)
    (tool / "proton").write_text("old")
    monkeypatch.setattr(proton_native, "in_use", lambda t: [4242])
    status = run()
    assert status.startswith("deferred")
    assert (tool / "proton").read_text() == "old"
    assert not (tool / "VERSION").exists()


def test_an_older_stamp_is_updated(setup):
    tools, _, run = setup
    tool = _existing_copy(tools)
    (tool / "VERSION").write_text("1:10.0-1\n")
    assert run().startswith("updated: 1:10.0-1 ->")
    assert (tool / "VERSION").read_text() == VERSION + "\n"


def test_in_use_sees_steam_and_processes_running_from_the_tool(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    tool = tmp_path / "tool"
    (tool / "files/bin").mkdir(parents=True)
    (tool / "files/bin/wine").write_text("")
    (tmp_path / "other").write_text("")
    for pid, target in (
        ("10", tool / "files/bin/wine"),
        ("11", tmp_path / "other"),
        ("13", tmp_path / "gone"),
    ):
        (proc / pid).mkdir(parents=True)
        os.symlink(target, proc / pid / "exe")
    (proc / "self").mkdir()
    (proc / "12").mkdir()
    monkeypatch.setattr(proton_native.recognize, "PROC_DIR", proc)
    monkeypatch.setattr(proton_native.recognize, "steam_client_pids", lambda: [99])
    assert proton_native.in_use(tool) == [99, 10]
