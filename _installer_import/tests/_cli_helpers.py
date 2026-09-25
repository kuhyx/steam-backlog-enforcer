"""Stubs shared by the CLI flow tests (plain functions, not fixtures)."""

from steam_installer import depotdl, steamcmd_validate

ARGV = ["--appid", "1771300", "--username", "u", "--language", "english"]


def _stub_download(monkeypatch, returncode=0):
    monkeypatch.setattr(depotdl, "download", lambda **kw: returncode)


def _stub_steamcmd(monkeypatch, returncode, crashed=False):
    monkeypatch.setattr(
        steamcmd_validate,
        "run_steamcmd_validate",
        lambda appid, username, logger: steamcmd_validate.ValidateResult(
            completed=returncode == 0,
            crashed_on_install_script=crashed,
            returncode=returncode,
        ),
    )
