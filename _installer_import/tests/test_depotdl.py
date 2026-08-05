import logging

from steam_installer import depotdl


def _capture(monkeypatch):
    """Intercept the subprocess call and hand back the argv it was given."""
    seen = {}

    def fake_run_logged(cmd, logger, timeout=None):
        seen["cmd"] = cmd
        return seen.get("rc", 0), ""

    monkeypatch.setattr(depotdl.runlog, "run_logged", fake_run_logged)
    return seen


def test_download_builds_expected_argv(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)

    depotdl.download(
        appid=1771300,
        install_dir=tmp_path / "Game",
        username="krzys2000",
        logger=logging.getLogger("t"),
        language="english",
        max_downloads=32,
    )

    cmd = seen["cmd"]
    assert cmd[0] == "depotdownloader"
    pairs = dict(zip(cmd[1::2], cmd[2::2]))
    assert pairs["-app"] == "1771300"
    assert pairs["-language"] == "english"
    assert pairs["-max-downloads"] == "32"
    assert pairs["-username"] == "krzys2000"


def test_download_always_passes_os_windows(tmp_path, monkeypatch):
    """Without -os, depotdownloader defaults to the host OS and can filter out
    every real (Windows-tagged) depot -- the original "0 bytes from 0 depots"."""
    seen = _capture(monkeypatch)

    depotdl.download(
        appid=1771300,
        install_dir=tmp_path / "Game",
        username="u",
        logger=logging.getLogger("t"),
    )

    cmd = seen["cmd"]
    assert cmd[cmd.index("-os") + 1] == "windows"
    assert "-remember-password" in cmd


def test_download_creates_the_install_dir(tmp_path, monkeypatch):
    _capture(monkeypatch)
    target = tmp_path / "nested" / "Game"

    depotdl.download(
        appid=1, install_dir=target, username="u", logger=logging.getLogger("t")
    )

    assert target.is_dir()


def test_download_returns_the_exit_code_instead_of_raising(tmp_path, monkeypatch):
    """The caller must distinguish "download failed" from "manifest step failed"
    to decide whether touching the manifest is safe at all."""
    seen = _capture(monkeypatch)
    seen["rc"] = 1

    returncode = depotdl.download(
        appid=1,
        install_dir=tmp_path / "Game",
        username="u",
        logger=logging.getLogger("t"),
    )

    assert returncode == 1
