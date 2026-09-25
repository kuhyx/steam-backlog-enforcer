"""Fixtures-as-functions shared by the recognize/manifest test files."""

from pathlib import Path

from steam_installer import vdf


def _write_partial_manifest(steamapps: Path, appid: int) -> None:
    steamapps.mkdir(parents=True, exist_ok=True)
    data = {
        "appid": str(appid),
        "StateFlags": "1026",
        "buildid": "23914554",
        "SharedDepots": {"228989": "228980"},
    }
    (steamapps / f"appmanifest_{appid}.acf").write_text(vdf.dumps("AppState", data))


def _fake_proc(tmp_path, entries):
    """Build a /proc-shaped tree: {pid: exe_target_path_or_None}."""
    proc = tmp_path / "proc"
    proc.mkdir()
    for name, target in entries.items():
        entry = proc / name
        entry.mkdir()
        if target is not None:
            real = tmp_path / "bin" / target
            real.parent.mkdir(parents=True, exist_ok=True)
            real.write_text("")
            (entry / "exe").symlink_to(real)
    return proc
