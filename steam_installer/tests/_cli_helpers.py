"""Stubs shared by the CLI flow tests (plain functions, not fixtures)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_installer import appinfo, depotdl, recognize

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

ARGV = ["--appid", "1771300", "--username", "u", "--language", "english"]


def _stub_download(monkeypatch: pytest.MonkeyPatch, returncode: int = 0) -> None:
    monkeypatch.setattr(depotdl, "download", lambda appid, pull, logger: returncode)


def proven_plan(
    monkeypatch: pytest.MonkeyPatch,
    install_dir: Path,
    shared_owner: dict[str, str] | None = None,
    shared: set[str] | None = None,
) -> str:
    """Stub the depot plan so the cached manifest proves the public build.

    *shared* defaults to the depots *shared_owner* names. Returns the gid.
    """
    gid = next(iter(recognize.discover_cached_depot_manifests(install_dir).values()))
    shared_depots = set(shared_owner or ()) if shared is None else shared
    monkeypatch.setattr(
        appinfo,
        "get_depot_plan",
        lambda appid, language: appinfo.DepotPlan(
            {"1771303"},
            shared_depots,
            manifests={"1771303": gid},
            shared_owner=dict(shared_owner or {}),
        ),
    )
    return gid
