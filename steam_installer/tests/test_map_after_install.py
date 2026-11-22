"""Mapping the native Proton right after an install, and when it must not."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_installer import (
    anticheat,
    cli,
    compat_apply,
    recognize,
)
from steam_installer.tests._acf_helpers import stamp_native_tool
from steam_installer.tests._cli_helpers import ARGV, _stub_download
from steam_installer.tests._map_data import (
    CONFIG,
    LOCKED,
    PLAIN,
    _mapped,
)

if TYPE_CHECKING:
    from pathlib import Path

    from steam_installer.library import SteamLibrary


pytestmark = pytest.mark.usefixtures("cli_logs")


def test_an_install_maps_the_game_while_steam_is_closed(
    steam: tuple[SteamLibrary, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An install maps the game while steam is closed."""
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch)
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir)
    assert cli.main(ARGV) == 0
    assert _mapped(library.path, 1771300) == ("proton-cachyos-native", "250")
    assert "mapped to proton-cachyos-native" in capsys.readouterr().out


def test_valve_proton_keeps_valves_default_for_one_run(
    steam: tuple[SteamLibrary, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valve proton keeps valves default for one run."""
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch)
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir)
    assert cli.main([*ARGV, "--valve-proton"]) == 0
    assert _mapped(library.path, 1771300) is None
    assert "Valve default: override: --valve-proton" in capsys.readouterr().out


def test_a_mapping_failure_leaves_the_install_on_valves_default(
    steam: tuple[SteamLibrary, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The install itself succeeded; the game still runs on Valve's Proton."""
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch)
    (library.path / "config" / "config.vdf").write_text("broken {")
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir)
    assert cli.main(ARGV) == 0
    assert "stays on Valve's default" in capsys.readouterr().out


def test_an_owned_dlc_download_keeps_valves_default(
    steam: tuple[SteamLibrary, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An owned dlc download keeps valves default."""
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch)
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir, dlc={"1771303": "9"})
    assert cli.main(ARGV) == 0
    assert "Valve default: owned DLC" in capsys.readouterr().out


def _with_compat_home(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.vdf").write_text(CONFIG)
    stamp_native_tool(root, LOCKED)
    monkeypatch.setattr(anticheat, "_download", lambda: b"[]")


def _proven(
    monkeypatch: pytest.MonkeyPatch,
    install_dir: Path,
    dlc: dict[str, str] | None = None,
) -> None:
    gid = next(iter(recognize.discover_cached_depot_manifests(install_dir).values()))
    plan = compat_apply.appinfo.DepotPlan(
        {"1771303"}, set(), manifests={"1771303": gid}, dlc=dict(dlc or {})
    )
    monkeypatch.setattr(
        compat_apply.appinfo, "get_depot_plan", lambda appid, language: plan
    )
