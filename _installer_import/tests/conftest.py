"""Shared test setup and fixtures.

`test_module_is_runnable_as_a_script` runs `python -m steam_installer.cli` in a
subprocess. Without the hook below, coverage collected in that child is thrown
away and the `__main__` guard looks uncovered.

The Steam-tree fixtures live here rather than in one test module because
several files need them, and importing a fixture across test modules confuses
both pytest and the linter.
"""

import logging
import os
import pathlib

import pytest

from steam_installer import (
    appinfo,
    cli,
    config,
    depotdl,
    deps,
    recognize,
    runlog,
    vdf,
)
from steam_installer.library import SteamLibrary


@pytest.fixture
def coverage_subprocess_env():
    """Env for a child process that should also record coverage."""
    env = os.environ.copy()
    root = pathlib.Path(__file__).resolve().parent.parent
    env["COVERAGE_PROCESS_START"] = str(root / "pyproject.toml")
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    return env


GHOST_ACF = """"AppState"
{
\t"appid"\t\t"284160"
\t"universe"\t\t"1"
\t"name"\t\t"BeamNG.drive"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"BeamNG.drive"
\t"LastUpdated"\t\t"0"
\t"SizeOnDisk"\t\t"0"
\t"StagingSize"\t\t"0"
\t"buildid"\t\t"24617469"
\t"DownloadType"\t\t"1"
\t"BytesToDownload"\t\t"0"
\t"BytesDownloaded"\t\t"0"
\t"TargetBuildID"\t\t"24617469"
\t"InstalledDepots"
\t{
\t}
\t"UserConfig"
\t{
\t\t"language"\t\t"english"
\t}
}
"""


@pytest.fixture
def library(tmp_path):
    lib = SteamLibrary(tmp_path / "Steam")
    lib.steamapps.mkdir(parents=True)
    lib.common.mkdir(parents=True)
    return lib


def _write(library, appid, text):
    path = library.steamapps / f"appmanifest_{appid}.acf"
    path.write_text(text)
    return path


def _real_install(library, appid=475150, installdir="RealGame", size="13908166765"):
    """A manifest shaped like the genuinely installed apps in a live library."""
    _write(
        library,
        appid,
        vdf.dumps(
            "AppState",
            {
                "appid": str(appid),
                "StateFlags": "4",
                "installdir": installdir,
                "SizeOnDisk": size,
                "InstalledDepots": {"475151": {"manifest": "123"}},
            },
        ),
    )
    content = library.common / installdir
    content.mkdir(parents=True, exist_ok=True)
    (content / "game.pak").write_bytes(b"x" * 4096)
    return content


@pytest.fixture
def isolated_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "LOG_DIR", tmp_path / "state")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config")
    monkeypatch.delenv(config.ENV_VAR, raising=False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(recognize, "steam_client_pids", list)
    yield
    logger = logging.getLogger(runlog.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def cli_steam(tmp_path, monkeypatch, isolated_cli):
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    library.common.mkdir(parents=True)
    monkeypatch.setattr(cli, "find_steam_root", lambda: library.path)
    monkeypatch.setattr(cli, "list_libraries", lambda root: [library])
    monkeypatch.setattr(
        appinfo,
        "get_metadata",
        lambda appid: appinfo.AppMetadata(appid, "BeamNG.drive", "BeamNG.drive"),
    )
    monkeypatch.setattr(
        depotdl, "download", lambda **kw: pytest.fail("must not download")
    )
    return library
