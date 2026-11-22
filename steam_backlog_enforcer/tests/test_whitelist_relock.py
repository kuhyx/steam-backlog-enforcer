"""Re-locking the exceptions file after a write, and saying so when it fails.

``_try_set_immutable`` used to fail silently, so a write that left the file
unlocked looked like success. A direct write now fails loudly; the enforce
loop's per-tick lock stays best-effort but warns once when the flag will not
stick.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _whitelist_locking as wl
from steam_backlog_enforcer import _whitelist_relock as relock_mod

# The real function: conftest swaps ``wl._relock`` for "always locked",
# since a non-root test can never set +i.
from steam_backlog_enforcer._whitelist_locking import (
    _relock as real_relock,
)
from steam_backlog_enforcer._whitelist_locking import (
    _try_set_immutable,
)
from steam_backlog_enforcer._whitelist_relock import (
    ExceptionNotLockedError,
    hand_back_to_dir_owner,
)
from steam_backlog_enforcer.tests._main_helpers import VALID_REASON


def test_add_raises_after_saving_when_not_relocked() -> None:
    """The entry and the audit line stay; the caller hears it failed."""
    with (
        patch.object(wl, "_relock", return_value=False),
        pytest.raises(ExceptionNotLockedError, match="not locked"),
    ):
        wl.add_pending_exception(440, VALID_REASON)
    assert wl.get_approved_exception_ids() == frozenset({440})
    assert "APPROVED | app_id=440" in wl.EXCEPTION_AUDIT_LOG.read_text(encoding="utf-8")


def test_real_relock_reports_flag_state(tmp_path: Path) -> None:
    """True only when the flag reads back as set after chattr."""
    target = tmp_path / "f.json"
    target.write_text("[]", encoding="utf-8")
    with patch.object(wl, "_immutable_flag_is", return_value=True):
        assert real_relock(target) is True
    with (
        patch("shutil.which", return_value=None),
        patch.object(wl, "_immutable_flag_is", return_value=False),
    ):
        assert real_relock(target) is False


def test_try_set_immutable_reports_missing_file_as_nothing_to_do(
    tmp_path: Path,
) -> None:
    """A file that does not exist has nothing to lock."""
    assert _try_set_immutable(tmp_path / "absent", immutable=True) is True


def test_hand_back_chowns_to_dir_owner(tmp_path: Path) -> None:
    """A file root just created goes back to the config dir's owner."""
    target = tmp_path / "f.json"
    target.write_text("[]", encoding="utf-8")
    dir_stat = tmp_path.stat()
    root_owned = os.stat_result((0, 0, 0, 0, 0, 0, 0, 0, 0, 0))  # uid 0, gid 0
    real_stat = Path.stat

    def _stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if self == target:
            return root_owned
        return real_stat(self, follow_symlinks=follow_symlinks)

    with (
        patch.object(Path, "stat", autospec=True, side_effect=_stat),
        patch("os.chown") as chown,
    ):
        hand_back_to_dir_owner(target)
    chown.assert_called_once_with(target, dir_stat.st_uid, dir_stat.st_gid)


def test_hand_back_leaves_matching_owner_alone(tmp_path: Path) -> None:
    """Same owner as the dir: no chown at all."""
    target = tmp_path / "f.json"
    target.write_text("[]", encoding="utf-8")
    with patch("os.chown") as chown:
        hand_back_to_dir_owner(target)
    chown.assert_not_called()


def test_hand_back_ignores_missing_file(tmp_path: Path) -> None:
    """A missing file is not an error."""
    hand_back_to_dir_owner(tmp_path / "absent")


class TestLockWarning:
    """The enforce loop warns once when the flag will not stick, not per tick."""

    @pytest.fixture(autouse=True)
    def _fresh(self) -> None:
        relock_mod.reset_lock_warnings()

    def test_warns_once_then_notes_recovery(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Three failing ticks: one warning. Then it holds: one recovery line."""
        cfg = tmp_path / "config.json"
        caplog.set_level(logging.INFO, logger=relock_mod.__name__)
        with patch.object(wl, "_try_set_immutable", return_value=False):
            for _ in range(3):
                wl.lock_enforcement_files(cfg)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        # Two files, each warned once.
        assert len(warnings) == 2
        assert all("immutable flag did not stick" in r.getMessage() for r in warnings)
        caplog.clear()
        with patch.object(wl, "_try_set_immutable", return_value=True):
            wl.lock_enforcement_files(cfg)
            wl.lock_enforcement_files(cfg)
        assert [r.levelno for r in caplog.records] == [logging.INFO, logging.INFO]

    def test_silent_while_flag_holds(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No log line at all when the flag holds every tick."""
        caplog.set_level(logging.INFO, logger=relock_mod.__name__)
        with patch.object(wl, "_try_set_immutable", return_value=True):
            for _ in range(3):
                wl.lock_enforcement_files(tmp_path / "config.json")
        assert caplog.records == []
