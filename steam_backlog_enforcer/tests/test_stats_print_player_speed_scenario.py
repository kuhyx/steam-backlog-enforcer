"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _print_player_speed_scenario,
)
from steam_backlog_enforcer._web_dataset import PaceVsHLTB
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._stats"


def _game(
    app_id: int = 1,
    name: str = "G",
    hours: float = 10.0,
    total: int = 10,
    unlocked: int = 0,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=5,
        count_comp=20,
    )


def _unplayable_rating(app_id: int) -> ProtonDBRating:
    return ProtonDBRating(app_id=app_id, tier="borked")


class TestPrintPlayerSpeedScenario:
    """Tests for _print_player_speed_scenario — 100 % branch coverage."""

    def _echoed(
        self,
        pace: PaceVsHLTB | None,
        rush: float = 100.0,
        leisure: float = 200.0,
    ) -> list[str]:
        """Test echoed."""
        out: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: out.append(a[0])):
            _print_player_speed_scenario(pace, rush, leisure)
        return out

    def test_none_pace_shows_no_calibration_message(self) -> None:
        """Test none pace shows no calibration message."""
        echoed = self._echoed(None)
        assert any("No calibration data" in s for s in echoed)

    def test_zero_calibration_count_shows_no_calibration_message(self) -> None:
        """Test zero calibration count shows no calibration message."""
        pace = PaceVsHLTB(
            calibration_count=0,
            ratio_vs_rush=-1.0,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace)
        assert any("No calibration data" in s for s in echoed)

    def test_ratio_vs_rush_shown_when_positive(self) -> None:
        """Test ratio vs rush shown when positive."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.05,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace)
        assert any("rush pace" in s for s in echoed)

    def test_ratio_vs_leisure_shown_when_positive(self) -> None:
        """Test ratio vs leisure shown when positive."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.05,
            ratio_vs_leisure=0.5,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace)
        assert any("leisure pace" in s for s in echoed)

    def test_interpolation_t_shown_when_not_minus_one(self) -> None:
        """Test interpolation t shown when not minus one."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.05,
            ratio_vs_leisure=0.5,
            interpolation_t=0.1,
            player_style="rush_to_leisure",
        )
        echoed = self._echoed(pace)
        assert any("Interpolation t" in s for s in echoed)

    def test_estimate_uses_interpolation_when_available(self) -> None:
        # rush=100, leisure=200, t=0.5 → est=150
        """Test estimate uses interpolation when available."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.5,
            ratio_vs_leisure=0.5,
            interpolation_t=0.5,
            player_style="rush_to_leisure",
        )
        echoed = self._echoed(pace, rush=100.0, leisure=200.0)
        assert any("150" in s for s in echoed)

    def test_estimate_falls_back_to_ratio_when_no_interpolation(self) -> None:
        # interpolation_t=-1, ratio_vs_rush=2.0, rush=100 → est=200
        """Test estimate falls back to ratio when no interpolation."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=2.0,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace, rush=100.0, leisure=0.0)
        assert any("200" in s for s in echoed)

    def test_no_estimate_when_both_methods_unavailable(self) -> None:
        """No 'Estimated backlog total' line when t=-1 and ratio=-1."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=-1.0,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace, rush=100.0, leisure=0.0)
        assert not any("Estimated backlog total" in s for s in echoed)

    def test_no_estimate_when_rush_total_zero_and_no_interpolation(self) -> None:
        """No estimate line when rush_total=0 and interpolation_t=-1."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.5,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace, rush=0.0, leisure=0.0)
        assert not any("Estimated backlog total" in s for s in echoed)
