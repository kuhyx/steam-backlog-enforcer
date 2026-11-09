"""A failed HLTB batch leaves every cached entry point's cache alone.

No network: the batch functions are faked at the module boundary.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer import _hltb_cached, _hltb_confidence
from steam_backlog_enforcer._hltb_failures import HLTBUnavailableError

_CONF = "steam_backlog_enforcer._hltb_confidence"
_DOWN = HLTBUnavailableError("HLTB: rate-limited, nothing refreshed")


def _found(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    count_comp: dict[int, int],
    **_kw: object,
) -> list[object]:
    """Fake search that finds every game."""
    for aid, _name in games:
        cache[aid], polls[aid], count_comp[aid] = 5.0, 7, 40
    return []


def test_cached_fetch_saves_new_results() -> None:
    """Uncached games are searched and the result is saved."""
    with (
        patch(f"{_CONF}.fetch_hltb_confidence", side_effect=_found),
        patch(f"{_CONF}.save_hltb_cache") as save,
    ):
        result = _hltb_confidence.fetch_hltb_confidence_cached([(1, "Celeste")])
    assert result == {1: 5.0}
    save.assert_called_once()


def test_cached_fetch_keeps_cache_when_hltb_is_down() -> None:
    """An unavailable batch returns the cache as loaded and saves nothing."""
    with (
        patch(f"{_CONF}.load_hltb_cache", return_value={2: 9.0}),
        patch(f"{_CONF}.fetch_hltb_confidence", side_effect=_DOWN),
        patch(f"{_CONF}.save_hltb_cache") as save,
    ):
        result = _hltb_confidence.fetch_hltb_confidence_cached([(1, "Celeste")])
    assert result == {2: 9.0}
    save.assert_not_called()


def test_detail_missing_reports_nothing_fetched_when_hltb_is_down() -> None:
    """The detail backfill returns 0 and writes nothing when HLTB is down."""
    with (
        patch(f"{_CONF}.fetch_hltb_times_timed", side_effect=_DOWN),
        patch(f"{_CONF}.save_hltb_cache") as save,
    ):
        assert _hltb_confidence.fetch_hltb_detail_missing([(1, "Celeste")]) == 0
    save.assert_not_called()


def test_submit_url_is_none_when_hltb_is_down() -> None:
    """No URL instead of a crash when the lookup cannot run."""
    with patch(f"{_CONF}.fetch_hltb_times", side_effect=_DOWN):
        assert _hltb_confidence.get_hltb_submit_url("Celeste") is None


def test_refresh_keeps_cache_when_hltb_is_down() -> None:
    """A re-search that cannot run returns the loaded caches and saves nothing."""
    with (
        patch(f"{_CONF}.load_hltb_cache", return_value={1: 9.0}),
        patch(f"{_CONF}.load_hltb_polls_cache", return_value={1: 30}),
        patch(f"{_CONF}.load_hltb_count_comp_cache", return_value={1: 80}),
        patch(f"{_CONF}.fetch_hltb_confidence", side_effect=_DOWN),
        patch(f"{_CONF}.save_hltb_cache") as save,
    ):
        result = _hltb_confidence.refresh_confidence([(1, "Celeste")])
    assert result == ({1: 9.0}, {1: 30}, {1: 80})
    save.assert_not_called()


def test_times_cached_keeps_cache_when_hltb_is_down() -> None:
    """The times fetch returns the cache as loaded and saves nothing."""
    cached = "steam_backlog_enforcer._hltb_cached"
    with (
        patch(f"{cached}.load_hltb_cache", return_value={2: 9.0}),
        patch(f"{cached}.fetch_hltb_times_timed", side_effect=_DOWN),
        patch(f"{cached}.save_hltb_cache") as save,
    ):
        result = _hltb_cached.fetch_hltb_times_cached([(1, "Celeste")])
    assert result == {2: 9.0}
    save.assert_not_called()
