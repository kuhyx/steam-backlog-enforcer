"""DLC that ships as its own app: discovery, download, and crediting it in the manifest.

Shapes are taken from the real `app_info_print` of Cyberpunk 2077 (1091500) and
its DLC, 2025-09-25: Phantom Liberty (2138330) keeps its ~25 GB depot under its
own app id; 2060310 is listed in the game's own depots; 2441600 has none.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from steam_installer import appinfo, depotdl, deps, dlc, runlog

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from steam_installer.runlog import RunLog

pytestmark = pytest.mark.usefixtures("cli_logs")

# Every real depot that has content ships a manifest on the public branch.
_PUB = {"manifests": {"public": {"gid": "1"}}}

GAME = {
    "extended": {"listofdlc": "2060310,2138330,2441600"},
    "depots": {
        "1091501": {"config": {"oslist": "windows"}, **_PUB},
        "2060310": {"dlcappid": "2060310", "config": {"oslist": "windows"}, **_PUB},
    },
}
DLC_BLOCKS: dict[int, dict[str, object]] = {
    # Listed in the game's own depots: the base run already covers it.
    2060310: {"depots": {"2060310": {"dlcappid": "2060310"}}},
    # Its own depot, tagged with its own id -- exactly what it installs.
    2138330: {
        "depots": {
            "2138330": {"dlcappid": "2138330", "config": {"oslist": "windows"}, **_PUB},
            "2138331": {"config": {"oslist": "windows", "language": "german"}, **_PUB},
        }
    },
    2441600: {"common": {"name": "Pre-Order Bonus"}},
}


def _app_info(
    monkeypatch: pytest.MonkeyPatch,
    game: dict[str, object] | None = None,
    dlc_blocks: dict[int, dict[str, object]] | None = None,
) -> None:
    block = GAME if game is None else game
    blocks = DLC_BLOCKS if dlc_blocks is None else dlc_blocks
    monkeypatch.setattr(appinfo, "fetch_app_block", lambda appid: block)
    monkeypatch.setattr(
        appinfo, "cached_blocks", lambda ids: {i: blocks[i] for i in ids}
    )


def test_only_dlc_with_depots_of_its_own_needs_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only dlc with depots of its own needs a run."""
    _app_info(monkeypatch)
    assert appinfo.get_dlc_plans(1091500) == {2138330: {"2138330": "1"}}


@pytest.mark.parametrize("game", [{}, {"extended": "scalar"}, {"extended": {}}])
def test_a_game_without_dlc_needs_no_lookup(
    monkeypatch: pytest.MonkeyPatch, game: dict[str, object]
) -> None:
    """A game without dlc needs no lookup."""
    monkeypatch.setattr(appinfo, "fetch_app_block", lambda appid: game)
    monkeypatch.setattr(
        appinfo, "cached_blocks", lambda ids: pytest.fail("no lookup expected")
    )
    assert appinfo.get_dlc_plans(1) == {}


def test_a_game_with_no_depot_list_still_finds_its_dlc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A game with no depot list still finds its dlc."""
    _app_info(monkeypatch, game={"extended": {"listofdlc": "2138330"}})
    assert appinfo.get_dlc_plans(1091500) == {2138330: {"2138330": "1"}}


def test_depot_plan_tags_the_games_own_dlc_depots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Depot plan tags the games own dlc depots."""
    _app_info(monkeypatch)
    plan = appinfo.get_depot_plan(1091500)
    assert plan.required == {"1091501"}
    assert plan.dlc == {"2060310": "2060310"}


def _logged(monkeypatch: pytest.MonkeyPatch, returncode: int, output: str = "") -> None:
    monkeypatch.setattr(
        depotdl.runlog, "run_logged", lambda cmd, logger: (returncode, output)
    )


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (0, "", True),
        (1, "App 2441600 (Bonus) is not available from this account.", None),
        (1, "Connection lost", False),
    ],
)
def test_download_dlc_separates_not_owned_from_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: str,
    *,
    expected: bool | None,
) -> None:
    """Download dlc separates not owned from failed."""
    _logged(monkeypatch, returncode, output)
    pull = depotdl.Pull(tmp_path, "u")
    result = depotdl.download_dlc(2441600, pull, logging.getLogger("t"))
    assert result is expected


def test_the_managed_depotdownloader_wins_over_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The managed depotdownloader wins over path."""
    managed = tmp_path / "depotdownloader"
    managed.write_text("")
    managed.chmod(0o755)
    monkeypatch.setattr(deps, "MANAGED_DEPOTDOWNLOADER", managed)
    assert deps.depotdownloader_bin() == str(managed)


@pytest.fixture(name="run_log")
def _run_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[RunLog]:
    """The run log fixture."""
    monkeypatch.setattr(runlog, "LOG_DIR", tmp_path / "state")
    log = runlog.setup(1091500)
    yield log
    for handler in list(log.logger.handlers):
        log.logger.removeHandler(handler)
        handler.close()


def _download_owned(
    monkeypatch: pytest.MonkeyPatch,
    run_log: RunLog,
    tmp_path: Path,
    outcomes: dict[int, bool | None],
) -> appinfo.DepotPlan | None:
    monkeypatch.setattr(
        appinfo,
        "get_dlc_plans",
        lambda appid, language: {7: {"70": "g70"}, 8: {"80": "g80"}},
    )
    monkeypatch.setattr(
        depotdl, "download_dlc", lambda dlc_appid, pull, logger: outcomes[dlc_appid]
    )
    return dlc.download_owned(1, depotdl.Pull(tmp_path, "u", max_downloads=8), run_log)


def test_owned_dlc_is_returned_and_unowned_skipped(
    monkeypatch: pytest.MonkeyPatch, run_log: RunLog, tmp_path: Path
) -> None:
    """Owned dlc is returned and unowned skipped."""
    plan = _download_owned(monkeypatch, run_log, tmp_path, {7: True, 8: None})
    assert (plan.required, plan.dlc) == ({"70"}, {"70": "7"})
    # Its public gid too, so the finish check can prove the DLC's build.
    assert plan.manifests == {"70": "g70"}


def test_a_failed_dlc_download_aborts(
    monkeypatch: pytest.MonkeyPatch, run_log: RunLog, tmp_path: Path
) -> None:
    """A failed dlc download aborts."""
    assert _download_owned(monkeypatch, run_log, tmp_path, {7: False, 8: True}) is None


def test_a_dlc_with_a_malformed_depot_section_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dlc with a malformed depot section is skipped."""
    _app_info(monkeypatch, dlc_blocks={**DLC_BLOCKS, 2441600: {"depots": "scalar"}})
    assert appinfo.get_dlc_plans(1091500) == {2138330: {"2138330": "1"}}
