"""Stubs shared by the CLI flow tests (plain functions, not fixtures)."""

from steam_installer import depotdl

ARGV = ["--appid", "1771300", "--username", "u", "--language", "english"]


def _stub_download(monkeypatch, returncode=0):
    monkeypatch.setattr(depotdl, "download", lambda **kw: returncode)
