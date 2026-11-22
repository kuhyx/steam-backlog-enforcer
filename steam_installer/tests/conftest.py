"""Shared test setup and fixtures.

`test_module_is_runnable_as_a_script` runs `python -m steam_installer.cli` in a
subprocess. Without the hook below, coverage collected in that child is thrown
away and the `__main__` guard looks uncovered.

The Steam-tree fixtures live here rather than in one test module because
several files need them, and importing a fixture across test modules confuses
both pytest and the linter.
"""

from __future__ import annotations

import logging
import os
import pathlib
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import (
    anticheat,
    appinfo,
    appinfo_cache,
    cli,
    config,
    depotdl,
    deps,
    proton_native,
    proton_pkg,
    recognize,
    runlog,
    steamctl,
    vdf,
)
from steam_installer.library import SteamLibrary
from steam_installer.tests._proton_fixture import VERSION, Repo, build_repo, stop_agent

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steam_installer.tests._proton_fixture import Setup


@pytest.fixture
def coverage_subprocess_env() -> dict[str, str]:
    """Env for a child process that should also record coverage."""
    env = os.environ.copy()
    root = pathlib.Path(__file__).resolve().parents[2]
    env["COVERAGE_PROCESS_START"] = str(root / "pyproject.toml")
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    return env


@pytest.fixture(name="library")
def _library(tmp_path: Path) -> SteamLibrary:
    """The library fixture."""
    lib = SteamLibrary(tmp_path / "Steam")
    lib.steamapps.mkdir(parents=True)
    lib.common.mkdir(parents=True)
    return lib


@pytest.fixture
def isolated_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """The isolated cli fixture."""
    # Requested by name: pylint rejects an argument that is only there for its effect.
    request.getfixturevalue("cli_logs")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config")
    monkeypatch.delenv(config.ENV_VAR, raising=False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(recognize, "steam_client_pids", list)


@pytest.fixture
def cli_steam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> SteamLibrary:
    """A fake Steam library with the cli isolated from this machine's state."""
    # Requested by name: pylint rejects an argument that is only there for its effect.
    request.getfixturevalue("isolated_cli")
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
        depotdl, "download", lambda *a, **kw: pytest.fail("must not download")
    )
    return library


@pytest.fixture(autouse=True)
def _no_host_depotdownloader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let this machine's ~/.local/bin decide which binary a test sees."""
    monkeypatch.setattr(deps, "MANAGED_DEPOTDOWNLOADER", tmp_path / "absent")


@pytest.fixture
def cli_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The cli logs fixture."""
    monkeypatch.setattr(runlog, "LOG_DIR", tmp_path / "state")
    yield
    logger = logging.getLogger(runlog.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def steam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SteamLibrary, Path]:
    """A Steam tree with KCD2 downloaded but its manifest not yet finished."""
    root = tmp_path / "Steam"
    library = SteamLibrary(root)
    install_dir = library.common / "KingdomComeDeliverance2"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1999516201078544527.manifest").write_bytes(b"x")
    (install_dir / "game.pak").write_bytes(b"x" * 1000)
    library.steamapps.mkdir(parents=True, exist_ok=True)
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps(
            "AppState",
            {
                "appid": "1771300",
                "StateFlags": "1026",
                "buildid": "23914554",
                "BytesToDownload": "92009052960",
                "BytesDownloaded": "22129058224",
            },
        )
    )

    monkeypatch.setattr(cli, "find_steam_root", lambda: root)
    monkeypatch.setattr(cli, "list_libraries", lambda r: [library])
    monkeypatch.setattr(cli, "pick_install_target", lambda libs, d: install_dir)
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        appinfo,
        "get_metadata",
        lambda appid: appinfo.AppMetadata(appid, "KCD2", "KingdomComeDeliverance2"),
    )
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan({"1771303"}, {"228989"}),
    )
    monkeypatch.setattr(appinfo, "get_build_id", lambda appid: "23914554")
    # No DLC unless a test says so: the real lookup is a steamcmd call.
    monkeypatch.setattr(appinfo, "get_dlc_plans", lambda appid, language: {})
    monkeypatch.setattr(recognize, "steam_client_pids", list)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    # Prompting is tty-gated now, and pytest's stdin is not a tty.
    monkeypatch.setattr(cli, "_is_interactive", lambda args: True)
    return library, install_dir


@pytest.fixture(autouse=True)
def _no_live_compat_side_effects(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test may fetch the anti-cheat list or read the real app cache.

    The modules that test those seams themselves (with their own fakes) are
    exempt from the part they cover.
    """

    def offline() -> Never:
        msg = "tests are offline"
        raise OSError(msg)

    module = request.node.module.__name__.rsplit(".", 1)[-1]
    if not request.node.name.startswith("test_anticheat_download"):
        monkeypatch.setattr(anticheat, "_download", offline)
    monkeypatch.setattr(anticheat, "CACHE", tmp_path / "no-anticheat-cache.json")
    if module != "test_appinfo_cache":
        monkeypatch.setattr(
            appinfo_cache, "default_path", lambda: tmp_path / "no-appinfo.vdf"
        )
    # The live Steam client is never seen, stopped or started by a test: an
    # unstubbed --apply run once shut down and relaunched kuhy's real Steam.
    if module in ("test_steamctl", "test_recognize"):
        return  # these fake subprocess and /proc themselves
    monkeypatch.setattr(recognize, "steam_client_pids", list)
    monkeypatch.setattr(
        steamctl, "stop", lambda *a, **k: pytest.fail("real steam stop")
    )
    monkeypatch.setattr(
        steamctl, "start", lambda *a, **k: pytest.fail("real steam start")
    )


@pytest.fixture(name="repo", scope="module")
def _repo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Repo]:
    """The repo fixture."""
    built = build_repo(tmp_path_factory.mktemp("repo"))
    yield built
    stop_agent(built.gpg_home)


@pytest.fixture(name="mirror")
def _mirror(repo: Repo, tmp_path: Path) -> Path:
    """A private copy of the fake mirror a test may tamper with."""
    root = tmp_path / "mirror"
    shutil.copytree(repo.root, root)
    return root


@pytest.fixture
def setup(
    repo: Repo, mirror: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Setup:
    """The setup fixture."""
    tools = tmp_path / "compatibilitytools.d"
    tools.mkdir()
    lock = proton_pkg.Lock(
        "proton-cachyos-native", (mirror / "cachyos.db").as_uri(), VERSION, repo.sha256
    )
    monkeypatch.setattr(proton_native, "in_use", lambda tool: [])

    def run(**kw: object) -> str:
        return proton_native.ensure(
            tools, lock, key=repo.key, fingerprint=repo.fingerprint, **kw
        )

    return tools, lock, run
