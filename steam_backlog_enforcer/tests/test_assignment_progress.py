"""Tests for the "earn one new achievement" release rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from steam_backlog_enforcer._assignment_progress import (
    RELEASE_COOLDOWN_DAYS,
    assignment_baseline,
    iso_to_epoch,
    last_assigned_epoch,
    mark_finished,
    newest_unlock_since,
    record_assignment,
    release_game,
    release_verdict,
)
from steam_backlog_enforcer._config_groups import AssignmentTimes
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import AchievementInfo, GameInfo

ASSIGNED = datetime(2026, 9, 20, tzinfo=UTC)
BEFORE = int((ASSIGNED - timedelta(days=1)).timestamp())
AFTER = int((ASSIGNED + timedelta(days=1)).timestamp())
LATER = int((ASSIGNED + timedelta(days=2)).timestamp())


def game(*unlocks: tuple[str, int], total: int = 5, app_id: int = 1) -> GameInfo:
    """Build a GameInfo whose achievements unlocked at the given epochs.

    Args:
        unlocks: ``(display_name, unlock_time)`` per unlocked achievement.
        total: Total achievement count (locked ones fill the rest).
        app_id: Steam application id.

    Returns:
        The GameInfo.
    """
    achievements = [
        AchievementInfo(n, n, achieved=True, unlock_time=t) for n, t in unlocks
    ]
    achievements += [
        AchievementInfo(f"L{i}", f"L{i}", achieved=False, unlock_time=0)
        for i in range(total - len(unlocks))
    ]
    return GameInfo(
        app_id=app_id,
        name="G",
        total_achievements=total,
        unlocked_achievements=len(unlocks),
        playtime_minutes=60,
        achievements=achievements,
    )


def assigned_state(app_id: int = 1) -> State:
    """State whose current game *app_id* was assigned at ``ASSIGNED``."""
    return State(
        current_app_id=app_id,
        current_game_name="G",
        assignment=AssignmentTimes(current_assigned_at=ASSIGNED.isoformat()),
    )


class TestIsoToEpoch:
    """Parsing ISO stamps into epoch seconds."""

    def test_parses(self) -> None:
        """A valid ISO stamp becomes its epoch seconds."""
        assert iso_to_epoch(ASSIGNED.isoformat()) == ASSIGNED.timestamp()

    def test_empty_and_malformed_are_unknown(self) -> None:
        """Empty or malformed stamps parse as unknown."""
        assert iso_to_epoch("") is None
        assert iso_to_epoch("not a date") is None


class TestNewestUnlockSince:
    """Finding the newest unlock after the assignment baseline."""

    def test_picks_the_latest_unlock_after_the_baseline(self) -> None:
        """The latest unlock after the baseline is the one returned."""
        g = game(("old", BEFORE), ("a", AFTER), ("b", LATER))
        newest = newest_unlock_since(g, ASSIGNED.isoformat())
        assert newest is not None
        assert newest.display_name == "b"

    def test_unlocks_before_the_baseline_do_not_count(self) -> None:
        """Unlocks from before the baseline do not count."""
        assert newest_unlock_since(game(("old", BEFORE)), ASSIGNED.isoformat()) is None

    def test_unknown_baseline_never_counts(self) -> None:
        """An unknown baseline never counts any unlock."""
        assert newest_unlock_since(game(("a", AFTER)), "") is None


class TestAssignmentBaseline:
    """Which timestamp an assignment is measured from."""

    def test_active_pick_uses_its_started_at(self) -> None:
        """An active manual pick is measured from its own start."""
        state = assigned_state()
        state.manual_picks = [{"app_id": 1, "game_name": "G", "started_at": "P"}]
        assert assignment_baseline(state, 1) == "P"

    def test_released_pick_falls_back_to_the_assignment(self) -> None:
        """A released pick falls back to the assignment stamp."""
        state = assigned_state()
        state.manual_picks = [
            {"app_id": 1, "game_name": "G", "started_at": "P", "released_at": "R"}
        ]
        assert assignment_baseline(state, 1) == ASSIGNED.isoformat()

    def test_unassigned_game_has_no_baseline(self) -> None:
        """A game that is not assigned has no baseline."""
        assert assignment_baseline(assigned_state(), 2) == ""


class TestReleaseVerdict:
    """Deciding whether the current game may be released."""

    def test_new_achievement_releases(self) -> None:
        """A new achievement since assignment releases the game."""
        released, why = release_verdict(assigned_state(), game(("Win", AFTER)))
        assert released is True
        assert "NEW ACHIEVEMENT on G: 'Win'" in why

    def test_complete_releases_even_without_a_new_unlock(self) -> None:
        """A 100% game releases even without a new unlock."""
        released, why = release_verdict(assigned_state(), game(("a", BEFORE), total=1))
        assert released is True
        assert "100%" in why

    def test_no_new_achievement_keeps_the_game(self) -> None:
        """No new achievement keeps the game and names the baseline date."""
        released, why = release_verdict(assigned_state(), game(("a", BEFORE)))
        assert released is False
        assert "No new achievement since 2026-09-20" in why

    def test_no_baseline_is_named_generically(self) -> None:
        """Without a baseline the reason names the assignment generically."""
        released, why = release_verdict(State(), game())
        assert released is False
        assert "since its assignment" in why


class TestRecordAssignment:
    """Stamping a fresh assignment into state."""

    def test_stamps_current_and_history(self) -> None:
        """Assigning stamps the current game, history and enforcement start."""
        state = State()
        record_assignment(state, 7, "Seven", at="T")
        assert (state.current_app_id, state.current_game_name) == (7, "Seven")
        assert state.assignment.current_assigned_at == "T"
        assert state.assignment.last_assigned_at == {"7": "T"}
        assert state.enforcement_started_at == "T"

    def test_keeps_the_first_enforcement_start(self) -> None:
        """A later assignment keeps the first enforcement start."""
        state = State(enforcement_started_at="FIRST")
        record_assignment(state, 7, "Seven")
        assert state.enforcement_started_at == "FIRST"
        assert iso_to_epoch(state.assignment.current_assigned_at) is not None


class TestLastAssignedEpoch:
    """Reading back when a game was last assigned."""

    def test_never_assigned_sorts_first(self) -> None:
        """A never-assigned game reads as epoch zero so it sorts first."""
        assert last_assigned_epoch(State(), 1) == 0.0

    def test_reads_the_stamp(self) -> None:
        """A stored stamp reads back as its epoch seconds."""
        state = State(
            assignment=AssignmentTimes(last_assigned_at={"1": ASSIGNED.isoformat()})
        )
        assert last_assigned_epoch(state, 1) == ASSIGNED.timestamp()


class TestMarkFinished:
    """Recording a finished game."""

    def test_records_once(self) -> None:
        """A game is recorded as finished only once."""
        state = State()
        assert mark_finished(state, 7) is True
        assert mark_finished(state, 7) is False
        assert state.finished_app_ids == [7]


class TestReleaseGame:
    """Releasing the current game."""

    def test_below_100_is_not_finished_but_cools_down(self) -> None:
        """A partial game is released and cooled down, not finished."""
        state = assigned_state()
        state.manual_picks = [{"app_id": 1, "game_name": "G", "started_at": "P"}]
        release_game(state, game(("a", AFTER)))
        assert state.finished_app_ids == []
        assert state.manual_picks[0]["released_at"]
        assert "1" in state.assignment.released_at
        expiry = datetime.fromisoformat(state.skipped_until["1"])
        assert expiry > datetime.now(UTC) + timedelta(days=RELEASE_COOLDOWN_DAYS - 1)

    def test_complete_game_is_finished(self) -> None:
        """A 100% game is recorded as finished on release."""
        state = assigned_state()
        release_game(state, game(("a", AFTER), total=1))
        assert state.finished_app_ids == [1]

    def test_keeps_an_earlier_pick_release_time(self) -> None:
        """An earlier pick release time is kept, not overwritten."""
        state = assigned_state()
        state.manual_picks = [
            {"app_id": 1, "game_name": "G", "started_at": "P", "released_at": "R"}
        ]
        release_game(state, game(("a", AFTER)))
        assert state.manual_picks[0]["released_at"] == "R"
