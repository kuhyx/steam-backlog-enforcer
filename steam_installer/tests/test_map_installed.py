"""Mapping games to the native Proton: after an install, and for the whole library."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import (
    cli,
    compat_map,
    recognize,
    steamctl,
    vdf,
)
from steam_installer.tests._map_data import (
    CS,
    NATIVE,
    PLAIN,
    SHARED,
    TOOL,
    _mapped,
)
from steam_installer.tests._steam_root import build_root

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.usefixtures("cli_logs")


@pytest.fixture(name="home")
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Steam root: config.vdf, the stamped tool, an app cache, anti-cheat list."""
    root = build_root(
        tmp_path,
        monkeypatch,
        cached={10: PLAIN, 20: NATIVE, 30: SHARED, 730: CS, 1493710: TOOL},
        installed=(10, 20, 1493710),
        anticheat_json=b'[{"storeIds": {"steam": "730"}}]',
    )
    monkeypatch.setattr(cli, "find_steam_root", lambda: root)
    return root


def test_dry_run_lists_decisions_and_writes_nothing(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dry run lists decisions and writes nothing."""
    before = (home / "config" / "config.vdf").read_bytes()
    assert cli.main(["--map-installed"]) == 0
    out = capsys.readouterr().out
    assert "10 Plain: map" in out
    assert "20 Native: Valve default: native" in out
    assert "1493710" not in out  # a tool, not a game
    assert "Dry run" in out
    assert (home / "config" / "config.vdf").read_bytes() == before


@pytest.mark.usefixtures("home")
def test_appids_decides_any_cached_app(capsys: pytest.CaptureFixture[str]) -> None:
    """Appids decides any cached app."""
    assert cli.main(["--map-installed", "--appids", "730,20,30,10,999"]) == 0
    out = capsys.readouterr().out
    assert "730 CS: Valve default: anti-cheat, native" in out
    assert "30 Shared: Valve default: shared depots" in out
    assert "10 Plain: map" in out
    assert "999: not in Steam's app cache" in out


def test_apply_maps_the_safe_ones_and_a_rerun_changes_nothing(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Apply maps the safe ones and a rerun changes nothing."""
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert _mapped(home, 10) == ("proton-cachyos-native", "250")
    assert _mapped(home, 20) is None
    once = (home / "config" / "config.vdf").read_bytes()
    capsys.readouterr()
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert "10 Plain: map -- already mapped" in capsys.readouterr().out
    assert (home / "config" / "config.vdf").read_bytes() == once


def test_apply_closes_steam_first_and_restarts_it(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply closes steam first and restarts it."""
    events = []
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [] if events else [5])

    def stop(_logger: object) -> bool:
        events.append("stop")
        return True

    monkeypatch.setattr(steamctl, "stop", stop)
    monkeypatch.setattr(steamctl, "start", lambda logger: events.append("start"))
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert events == ["stop", "start"]
    assert _mapped(home, 10) is not None


def test_apply_declined_writes_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply declined writes nothing."""
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [5])
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert cli.main(["--map-installed", "--apply"]) == 1
    assert _mapped(home, 10) is None


def test_a_kept_choice_and_a_write_error_are_reported(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A kept choice and a write error are reported."""
    config = home / "config" / "config.vdf"
    compat_map.map_app(config, 10)
    config.write_text(
        config.read_text().replace("proton-cachyos-native", "GE-Proton10")
    )
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert "kept: already mapped to GE-Proton10" in capsys.readouterr().out
    config.write_text("garbage {")
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 1


def test_owned_dlc_in_the_manifest_keeps_valves_default(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Owned dlc in the manifest keeps valves default."""
    manifest = home / "steamapps" / "appmanifest_10.acf"
    manifest.write_text(
        vdf.dumps(
            "AppState",
            {
                "appid": "10",
                "InstalledDepots": {
                    "11": {"manifest": "1"},
                    "12": {"manifest": "2", "dlcappid": "13"},
                },
            },
        )
    )
    assert cli.main(["--map-installed"]) == 0
    assert "10 Plain: Valve default: owned DLC" in capsys.readouterr().out


@pytest.mark.usefixtures("home")
def test_valve_proton_only_goes_with_an_install() -> None:
    """Valve proton only goes with an install."""
    with pytest.raises(SystemExit):
        cli.main(["--map-installed", "--valve-proton"])


def test_a_failed_write_stops_the_run(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed write stops the run."""

    def boom(_config: Path, _appid: int) -> Never:
        msg = "config.vdf line 3: unexpected layout"
        raise compat_map.CompatMapError(msg)

    monkeypatch.setattr(compat_map, "map_app", boom)
    (home / "steamapps" / "appmanifest_notanid.acf").write_text("x")
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "Mapping stopped" in out
    assert "config.vdf line 3" in out
