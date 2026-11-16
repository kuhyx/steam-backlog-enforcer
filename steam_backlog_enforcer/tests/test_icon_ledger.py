"""Tests for _icon_ledger: the icon-word ledger file (load, atomic save, corrupt)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _icon_ledger as mod

_GOOD = {
    "version": 1,
    "icons": {
        "nav.dashboard": {"word": "Home", "glyph": None},
        "cmd.done": {"word": None, "glyph": "🥇"},
        "cmd.scan": {"glyph": "📡"},
    },
}


@pytest.fixture(name="home")
def fixture_home(tmp_path: Path) -> Path:
    """An empty directory of its own (conftest fixtures also use tmp_path)."""
    path = tmp_path / "ledger_home"
    path.mkdir()
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestPath:
    """Where the ledger lives."""

    def test_default_is_the_repo_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without the env override the ledger is web/src/ui/icon_words.json."""
        monkeypatch.delenv(mod.LEDGER_ENV, raising=False)
        repo = Path(mod.__file__).resolve().parent.parent
        assert repo / "web" / "src" / "ui" / "icon_words.json" == mod.DEFAULT_LEDGER
        assert mod.ledger_path() == mod.DEFAULT_LEDGER

    def test_env_override_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """SBE_ICON_WORDS points the server at another file (scratch copies)."""
        monkeypatch.setenv(mod.LEDGER_ENV, str(tmp_path / "copy.json"))
        assert mod.ledger_path() == tmp_path / "copy.json"

    def test_tests_never_see_the_repo_file(self) -> None:
        """The autouse isolation redirects the ledger into tmp_path."""
        assert mod.ledger_path() != mod.DEFAULT_LEDGER

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("icon_words.json", True),
            ("icon_words.json.corrupt", True),
            (".icon_words.json.x1y2.tmp", True),
            ("icon_words.ts", False),
            ("registry.json", False),
        ],
    )
    def test_is_ledger_file(self, name: str, *, expected: bool) -> None:
        """The ledger, its temp files and corrupt copies are runtime data."""
        assert mod.is_ledger_file(Path("/x") / name) is expected


class TestLoad:
    """load_ledger: missing, valid and corrupt files."""

    def test_missing_file_is_an_empty_ledger(self, home: Path) -> None:
        """No file yet means nothing answered."""
        assert mod.load_ledger(home / "none.json") == {"version": 1, "icons": {}}

    def test_valid_file_round_trips(self, home: Path) -> None:
        """A valid file loads as written, a missing word key included."""
        path = home / "l.json"
        _write(path, json.dumps(_GOOD))
        assert mod.load_ledger(path) == _GOOD

    @pytest.mark.parametrize(
        "text",
        [
            "{not json",
            "[]",
            '{"version": 2, "icons": {}}',
            '{"version": 1, "icons": []}',
            '{"version": 1, "icons": {"a.b": "word"}}',
            '{"version": 1, "icons": {"a.b": {"word": 5}}}',
            '{"version": 1, "icons": {"a.b": {"glyph": ["x"]}}}',
            '{"version": 1, "icons": {"a.b": {"word": "x", "extra": 1}}}',
        ],
    )
    def test_corrupt_file_is_kept_aside_and_fails_loudly(
        self, home: Path, text: str
    ) -> None:
        """Bad JSON or schema: copied to .corrupt, original untouched, raises."""
        path = home / "l.json"
        _write(path, text)
        with pytest.raises(mod.LedgerCorruptError) as err:
            mod.load_ledger(path)
        kept = home / "l.json.corrupt"
        assert err.value.kept == kept
        assert kept.read_text("utf-8") == text
        assert path.read_text("utf-8") == text
        assert str(kept) in str(err.value)

    def test_same_corrupt_bytes_are_kept_once(self, home: Path) -> None:
        """Re-reading the same broken file does not pile up copies."""
        path = home / "l.json"
        _write(path, "{bad")
        for _ in range(2):
            with pytest.raises(mod.LedgerCorruptError):
                mod.load_ledger(path)
        assert sorted(p.name for p in home.iterdir()) == [
            "l.json",
            "l.json.corrupt",
        ]

    def test_older_corrupt_copy_is_never_overwritten(self, home: Path) -> None:
        """A different broken file gets its own copy; the first one survives."""
        path = home / "l.json"
        _write(home / "l.json.corrupt", "{first")
        _write(path, "{second")
        with pytest.raises(mod.LedgerCorruptError) as err:
            mod.load_ledger(path)
        assert (home / "l.json.corrupt").read_text("utf-8") == "{first"
        assert err.value.kept.name.startswith("l.json.corrupt.")
        assert err.value.kept.read_text("utf-8") == "{second"


class TestSave:
    """save_ledger: atomic, stable, readable."""

    def test_writes_sorted_indented_json_with_newline(self, home: Path) -> None:
        """Stable output so the user's commits diff cleanly; emoji kept raw."""
        path = home / "l.json"
        mod.save_ledger(path, _GOOD)
        text = path.read_text("utf-8")
        assert text.endswith("}\n")
        assert "🥇" in text
        assert json.loads(text) == _GOOD
        assert text.index('"cmd.done"') < text.index('"nav.dashboard"')
        assert stat.S_IMODE(path.stat().st_mode) == mod.FILE_MODE

    def test_replace_failure_leaves_the_old_file_and_no_temp(self, home: Path) -> None:
        """A failed rename keeps the previous ledger intact and cleans up."""
        path = home / "l.json"
        _write(path, json.dumps({"version": 1, "icons": {}}))
        with (
            patch.object(mod.os, "replace", side_effect=OSError("disk")),
            pytest.raises(OSError, match="disk"),
        ):
            mod.save_ledger(path, _GOOD)
        assert json.loads(path.read_text("utf-8")) == {"version": 1, "icons": {}}
        assert [p.name for p in home.iterdir()] == ["l.json"]

    def test_goes_through_a_temp_file_in_the_same_dir(self, home: Path) -> None:
        """The new content lands by rename from a sibling temp file."""
        path = home / mod.LEDGER_NAME
        seen: list[tuple[str, str]] = []
        real = os.replace

        def spy(src: str, dst: str) -> None:
            seen.append((src, dst))
            real(src, dst)

        with patch.object(mod.os, "replace", side_effect=spy):
            mod.save_ledger(path, _GOOD)
        assert len(seen) == 1
        src, dst = seen[0]
        assert Path(dst) == path
        assert Path(src).parent == home
        assert mod.is_ledger_file(Path(src))
