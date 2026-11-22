"""Mapping games to the native Proton: after an install, and for the whole library."""

import pytest
from _appinfo_blob import encode
from _cli_helpers import ARGV, _stub_download

from steam_installer import (
    anticheat,
    cli,
    compat_apply,
    compat_map,
    proton_pkg,
    recognize,
    steamctl,
    vdf,
)

pytestmark = pytest.mark.usefixtures("cli_logs")

LOCKED = proton_pkg.read_lock().version
CONFIG = '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t}\n\t\t}\n\t}\n}\n'
PLAIN = {"common": {"name": "Plain", "oslist": "windows", "type": "Game"},
         "depots": {"11": {"config": {"oslist": "windows"}}}}
NATIVE = {"common": {"name": "Native", "oslist": "windows,linux", "type": "Game"}}
SHARED = {"common": {"name": "Shared", "oslist": "windows", "type": "Game"},
          "depots": {"31": {"depotfromapp": "228980"}}}
CS = {"common": {"name": "CS", "oslist": "windows,linux", "type": "Game"}}
TOOL = {"common": {"name": "Proton Experimental", "type": "Tool"}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A Steam root with config.vdf, the stamped tool, an app cache and anti-cheat list."""
    root = tmp_path / "Steam"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.vdf").write_text(CONFIG)
    tool = root / "compatibilitytools.d" / "proton-cachyos-native"
    tool.mkdir(parents=True)
    (tool / "toolmanifest.vdf").write_text("x")
    (tool / "VERSION").write_text(LOCKED + "\n")
    cache = tmp_path / "appinfo.vdf"
    cache.write_bytes(encode({10: PLAIN, 20: NATIVE, 30: SHARED, 730: CS, 1493710: TOOL}))
    monkeypatch.setattr(compat_apply.appinfo.appinfo_cache, "default_path", lambda: cache)
    monkeypatch.setattr(anticheat, "_download", lambda: b'[{"storeIds": {"steam": "730"}}]')
    steamapps = root / "steamapps"
    steamapps.mkdir()
    for appid in (10, 20, 1493710):
        (steamapps / f"appmanifest_{appid}.acf").write_text(
            vdf.dumps("AppState", {"appid": str(appid), "InstalledDepots": {}}))
    monkeypatch.setattr(cli, "find_steam_root", lambda: root)
    return root


def _mapped(root, appid):
    return compat_map.current(root / "config" / "config.vdf", appid)


def test_dry_run_lists_decisions_and_writes_nothing(home, capsys):
    before = (home / "config" / "config.vdf").read_bytes()
    assert cli.main(["--map-installed"]) == 0
    out = capsys.readouterr().out
    assert "10 Plain: map" in out
    assert "20 Native: Valve default: native" in out
    assert "1493710" not in out  # a tool, not a game
    assert "Dry run" in out
    assert (home / "config" / "config.vdf").read_bytes() == before


def test_appids_decides_any_cached_app(home, capsys):
    assert cli.main(["--map-installed", "--appids", "730,20,30,10,999"]) == 0
    out = capsys.readouterr().out
    assert "730 CS: Valve default: anti-cheat, native" in out
    assert "30 Shared: Valve default: shared depots" in out
    assert "10 Plain: map" in out
    assert "999: not in Steam's app cache" in out


def test_apply_maps_the_safe_ones_and_a_rerun_changes_nothing(home, capsys):
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert _mapped(home, 10) == ("proton-cachyos-native", "250")
    assert _mapped(home, 20) is None
    once = (home / "config" / "config.vdf").read_bytes()
    capsys.readouterr()
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert "10 Plain: map -- already mapped" in capsys.readouterr().out
    assert (home / "config" / "config.vdf").read_bytes() == once


def test_apply_closes_steam_first_and_restarts_it(home, monkeypatch):
    events = []
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [] if events else [5])
    monkeypatch.setattr(steamctl, "stop", lambda logger: events.append("stop") or True)
    monkeypatch.setattr(steamctl, "start", lambda logger: events.append("start"))
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert events == ["stop", "start"]
    assert _mapped(home, 10) is not None


def test_apply_declined_writes_nothing(home, monkeypatch):
    monkeypatch.setattr(recognize, "steam_client_pids", lambda: [5])
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert cli.main(["--map-installed", "--apply"]) == 1
    assert _mapped(home, 10) is None


def test_a_kept_choice_and_a_write_error_are_reported(home, monkeypatch, capsys):
    config = home / "config" / "config.vdf"
    compat_map.map_app(config, 10)
    config.write_text(config.read_text().replace("proton-cachyos-native", "GE-Proton10"))
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 0
    assert "kept: already mapped to GE-Proton10" in capsys.readouterr().out
    config.write_text("garbage {")
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 1


def test_owned_dlc_in_the_manifest_keeps_valves_default(home, capsys):
    manifest = home / "steamapps" / "appmanifest_10.acf"
    manifest.write_text(vdf.dumps("AppState", {"appid": "10", "InstalledDepots": {
        "11": {"manifest": "1"}, "12": {"manifest": "2", "dlcappid": "13"}}}))
    assert cli.main(["--map-installed"]) == 0
    assert "10 Plain: Valve default: owned DLC" in capsys.readouterr().out


def test_valve_proton_only_goes_with_an_install(home):
    with pytest.raises(SystemExit):
        cli.main(["--map-installed", "--valve-proton"])


def test_an_install_maps_the_game_while_steam_is_closed(steam, monkeypatch, capsys, tmp_path):
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch, tmp_path)
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "_fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir)
    assert cli.main(ARGV) == 0
    assert _mapped(library.path, 1771300) == ("proton-cachyos-native", "250")
    assert "mapped to proton-cachyos-native" in capsys.readouterr().out


def test_valve_proton_keeps_valves_default_for_one_run(steam, monkeypatch, capsys, tmp_path):
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch, tmp_path)
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "_fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir)
    assert cli.main([*ARGV, "--valve-proton"]) == 0
    assert _mapped(library.path, 1771300) is None
    assert "Valve default: override: --valve-proton" in capsys.readouterr().out


def test_a_mapping_failure_leaves_the_install_on_valves_default(steam, monkeypatch, capsys, tmp_path):
    """The install itself succeeded; the game still runs on Valve's Proton."""
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch, tmp_path)
    (library.path / "config" / "config.vdf").write_text("broken {")
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "_fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir)
    assert cli.main(ARGV) == 0
    assert "stays on Valve's default" in capsys.readouterr().out


def test_an_owned_dlc_download_keeps_valves_default(steam, monkeypatch, capsys, tmp_path):
    library, install_dir = steam
    _with_compat_home(library.path, monkeypatch, tmp_path)
    _stub_download(monkeypatch)
    monkeypatch.setattr(compat_apply.appinfo, "_fetch_app_block", lambda appid: PLAIN)
    _proven(monkeypatch, install_dir, dlc={"1771303": "9"})
    assert cli.main(ARGV) == 0
    assert "Valve default: owned DLC" in capsys.readouterr().out


def _with_compat_home(root, monkeypatch, tmp_path):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.vdf").write_text(CONFIG)
    tool = root / "compatibilitytools.d" / "proton-cachyos-native"
    tool.mkdir(parents=True)
    (tool / "toolmanifest.vdf").write_text("x")
    (tool / "VERSION").write_text(LOCKED + "\n")
    monkeypatch.setattr(anticheat, "_download", lambda: b"[]")


def _proven(monkeypatch, install_dir, dlc=None):
    (gid,) = recognize.discover_cached_depot_manifests(install_dir).values()
    plan = compat_apply.appinfo.DepotPlan({"1771303"}, set(), manifests={"1771303": gid},
                                          dlc=dict(dlc or {}))
    monkeypatch.setattr(compat_apply.appinfo, "get_depot_plan", lambda appid, language: plan)


def test_a_failed_write_stops_the_run(home, monkeypatch, capsys):
    def boom(config, appid):
        raise compat_map.CompatMapError("config.vdf line 3: unexpected layout")

    monkeypatch.setattr(compat_map, "map_app", boom)
    (home / "steamapps" / "appmanifest_notanid.acf").write_text("x")
    assert cli.main(["--map-installed", "--apply", "--yes"]) == 1
    assert "Mapping stopped: config.vdf line 3" in capsys.readouterr().out
