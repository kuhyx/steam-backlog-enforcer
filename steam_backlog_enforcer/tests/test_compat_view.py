"""``GET /api/compat``: the map-installed decisions as rows, cached by file stats."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _compat_view, _web_routes
from steam_backlog_enforcer._command_params import InvalidParamsError
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._web_request import make_request
from steam_installer.appinfo import AppInfoError
from steam_installer.compat_rows import Row

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

V = "steam_backlog_enforcer._compat_view"


def _row(appid: int, *, changes: bool) -> Row:
    return Row(
        appid=appid,
        name=f"G{appid}",
        current=None,
        priority=None,
        decided="proton-cachyos-native" if changes else None,
        reasons=() if changes else ("native",),
        note=None,
        map=changes,
        changes=changes,
        cached=True,
    )


ROWS = [_row(10, changes=True), _row(20, changes=False), _row(30, changes=True)]


@pytest.fixture(name="env")
def _env() -> Iterator[dict[str, MagicMock]]:
    """A fake Steam root, a fixed stat key and the installer's rows mocked."""
    _compat_view.clear_cache()
    with (
        patch(f"{V}.find_steam_root", return_value=MagicMock()) as root,
        patch(f"{V}.cache_key", return_value=("k",)) as key,
        patch(f"{V}.Context") as context,
        patch(f"{V}.rows", return_value=ROWS) as rows,
    ):
        context.return_value.tool_ready = True
        yield {"root": root, "key": key, "context": context, "rows": rows}
    _compat_view.clear_cache()


def test_payload_shape(env: dict[str, MagicMock]) -> None:
    """Rows as the CompatRow contract, plus the tool and whether it is ready."""
    data = _compat_view.compat_payload()
    assert data["tool"] == "proton-cachyos-native"
    assert data["tool_ready"] is True
    rows = data["rows"]
    assert isinstance(rows, list)
    assert [r["app_id"] for r in rows] == [10, 20, 30]
    assert rows[1]["reasons"] == ["native"]
    _, kwargs = env["context"].call_args
    assert kwargs == {"anticheat_max_age": _compat_view.ANTICHEAT_MAX_AGE}


def test_same_key_is_served_from_memory(env: dict[str, MagicMock]) -> None:
    """A second GET with unchanged files decides nothing again."""
    _compat_view.compat_payload()
    _compat_view.compat_payload()
    env["rows"].assert_called_once()


def test_a_changed_file_recomputes(env: dict[str, MagicMock]) -> None:
    """Any stat change (config.vdf written by apply) is a fresh decision."""
    _compat_view.compat_payload()
    env["key"].return_value = ("k2",)
    _compat_view.compat_payload()
    assert env["rows"].call_count == 2


@pytest.mark.usefixtures("env")
def test_view_replies_ok() -> None:
    """The route answers 200 with the payload."""
    reply = _compat_view.compat_view(make_request())
    assert reply.status == 200
    assert isinstance(reply.payload, dict)


@pytest.mark.parametrize(
    "exc", [AppInfoError("no cache"), FileNotFoundError("no Steam"), ValueError("x")]
)
def test_view_failure_is_op_failed(env: dict[str, MagicMock], exc: Exception) -> None:
    """No app cache, no Steam or a bad overrides file is a 502, not a crash."""
    env["rows"].side_effect = exc
    with pytest.raises(ApiError) as err:
        _compat_view.compat_view(make_request())
    assert err.value.code == "op_failed"


def test_route_is_registered() -> None:
    """``GET /api/compat`` is in the route table."""
    assert any(
        e.method == "GET" and re.fullmatch(e.pattern, "/api/compat")
        for e in _web_routes.ROUTES
    )


def test_cache_key_tracks_the_files(tmp_path: Path) -> None:
    """The key changes when config.vdf or a manifest changes."""
    root = tmp_path / "Steam"
    (root / "config").mkdir(parents=True)
    (root / "steamapps").mkdir()
    config = root / "config" / "config.vdf"
    config.write_text("a")
    with patch(f"{V}.appinfo_cache.default_path", return_value=root / "none.vdf"):
        first = _compat_view.cache_key(root)
        config.write_text("ab")
        second = _compat_view.cache_key(root)
        (root / "steamapps" / "appmanifest_1.acf").write_text("x")
        third = _compat_view.cache_key(root)
    assert len({first, second, third}) == 3


class TestCheckedAppids:
    """The ``appids`` param: digits only, installed only, never empty."""

    @pytest.mark.usefixtures("env")
    def test_none_means_every_changing_game(self) -> None:
        """No appids: every row that would change."""
        assert _compat_view.checked_appids(None) == [10, 30]

    @pytest.mark.usefixtures("env")
    def test_list_is_parsed_and_deduped(self) -> None:
        """Spaces forgiven, duplicates dropped, order kept."""
        assert _compat_view.checked_appids(" 30, 10,30 ") == [30, 10]

    @pytest.mark.usefixtures("env")
    @pytest.mark.parametrize("raw", ["10,x", "10,,20", "-1", "10;20"])
    def test_junk_is_refused(self, raw: str) -> None:
        """Anything but comma-separated digits is invalid."""
        with pytest.raises(InvalidParamsError):
            _compat_view.checked_appids(raw)

    @pytest.mark.usefixtures("env")
    def test_a_game_that_is_not_installed_is_refused(self) -> None:
        """Apply never maps a game that is not installed."""
        with pytest.raises(InvalidParamsError, match="999"):
            _compat_view.checked_appids("10,999")

    def test_nothing_to_map_is_refused(self, env: dict[str, MagicMock]) -> None:
        """No changing game and no list: nothing to do is an error, not a no-op."""
        env["rows"].return_value = [_row(20, changes=False)]
        with pytest.raises(InvalidParamsError):
            _compat_view.checked_appids(None)

    @pytest.mark.usefixtures("env")
    def test_phrase_fields(self) -> None:
        """The phrase counts exactly the games the job will be given."""
        assert _compat_view.phrase_fields({"appids": "10,20"}) == {"appid_count": 2}
        assert _compat_view.phrase_fields({}) == {"appid_count": 2}
