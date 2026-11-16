"""Tests for _web_icon_words: the icon-word endpoints and the page injection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _icon_ledger, _web_icon_words, _web_routes
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._icon_registry import REGISTRY
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True, name="registry")
def fixture_registry(tmp_path: Path) -> Iterator[Path]:
    """A two-icon registry instead of the real one."""
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(REGISTRY), encoding="utf-8")
    with patch.object(_web_icon_words, "REGISTRY_FILE", path):
        yield path


def _set(icon: str, **body: object) -> dict[str, object]:
    reply = _web_icon_words.set_icon_word_view(
        make_request(icon, body=body, method="POST")
    )
    return payload_of(reply)


def _stored() -> dict[str, dict[str, object]]:
    return json.loads(_icon_ledger.ledger_path().read_text("utf-8"))["icons"]


def _refused(icon: str, code: str, **body: object) -> ApiError:
    with pytest.raises(ApiError) as err:
        _set(icon, **body)
    assert err.value.code == code
    return err.value


class TestWords:
    """POST /api/icon-words/<id> with a word."""

    def test_suggestion_is_saved_and_the_ledger_returned(self) -> None:
        """A picked word is stored and the whole ledger comes back."""
        out = _set("nav.dashboard", word="home")
        assert out == {
            "version": 1,
            "icons": {"nav.dashboard": {"word": "home", "glyph": None}},
        }
        assert _stored() == {"nav.dashboard": {"word": "home", "glyph": None}}

    def test_manual_multi_word_keeps_casing_and_collapses_spaces(self) -> None:
        """Any words are accepted; whitespace runs become one space."""
        _set("cmd.done", word="  I  got\tan HLTB\n win ")
        assert _stored()["cmd.done"] == {"word": "I got an HLTB win", "glyph": None}

    def test_forty_characters_is_the_limit(self) -> None:
        """40 characters pass; 41 are refused."""
        _set("cmd.done", word="x" * 40)
        _refused("cmd.done", "invalid_params", word="x" * 41)
        assert _stored()["cmd.done"]["word"] == "x" * 40

    @pytest.mark.parametrize(
        "word", ["", "   ", "bad\x00word", "esc\x1b", "del\x7f", 5, ["a"]]
    )
    def test_bad_words_are_refused(self, word: object) -> None:
        """Empty, control characters and non-strings are invalid_params (400)."""
        err = _refused("cmd.done", "invalid_params", word=word)
        assert err.status == 400
        assert not _icon_ledger.ledger_path().exists()

    def test_skip_stores_null(self) -> None:
        """word: null means skipped (no label), and counts as answered."""
        _set("cmd.done", word=None)
        assert _stored()["cmd.done"] == {"word": None, "glyph": None}


class TestGlyphs:
    """POST /api/icon-words/<id> with a glyph."""

    def test_alternative_is_saved_without_answering_the_word(self) -> None:
        """A glyph alone leaves the word unanswered (no word key)."""
        _set("cmd.done", glyph="🎉")
        assert _stored()["cmd.done"] == {"glyph": "🎉"}

    def test_word_survives_a_later_glyph_choice(self) -> None:
        """Word and glyph are independent."""
        _set("cmd.done", word="won")
        _set("cmd.done", glyph="🏁")
        assert _stored()["cmd.done"] == {"word": "won", "glyph": "🏁"}

    @pytest.mark.parametrize("glyph", ["🏆", None])
    def test_default_or_null_resets_to_default(self, glyph: object) -> None:
        """Choosing the default glyph is stored as null (keep default)."""
        _set("cmd.done", glyph="🎉")
        _set("cmd.done", glyph=glyph)
        assert _stored()["cmd.done"] == {"glyph": None}

    @pytest.mark.parametrize("glyph", ["🍕", "🏡", "", 3])
    def test_unregistered_glyph_is_refused(self, glyph: object) -> None:
        """Only the default or this icon's own 3 alternatives are accepted."""
        _refused("cmd.done", "invalid_params", glyph=glyph)


class TestRequestShape:
    """Unknown ids, empty and unknown bodies."""

    def test_unknown_id_is_not_found(self) -> None:
        """An id the registry lacks is a 404."""
        assert _refused("cmd.nope", "not_found", word="x").status == 404

    def test_empty_body_is_refused(self) -> None:
        """Neither word nor glyph: nothing to save."""
        _refused("cmd.done", "invalid_params")

    def test_unknown_key_is_refused(self) -> None:
        """A typo'd key is never silently ignored."""
        _refused("cmd.done", "invalid_params", word="x", colour="red")

    def test_missing_registry_fails_loudly(self, registry: Path) -> None:
        """Without the registry no glyph or id can be checked: op_failed."""
        registry.unlink()
        assert _refused("cmd.done", "op_failed", word="x").status == 500


class TestCorruptLedger:
    """A corrupt ledger is kept aside, reads and writes fail loudly."""

    def test_get_and_post_fail_and_the_file_is_untouched(self) -> None:
        """Nothing is overwritten while the ledger does not parse."""
        path = _icon_ledger.ledger_path()
        path.write_text("{broken", encoding="utf-8")
        with pytest.raises(ApiError) as err:
            _web_icon_words.icon_words_view(make_request())
        assert (err.value.code, err.value.status) == ("op_failed", 500)
        assert ".corrupt" in err.value.message
        _refused("cmd.done", "op_failed", word="x")
        assert path.read_text("utf-8") == "{broken"
        assert path.with_name(path.name + ".corrupt").read_text("utf-8") == "{broken"


class TestGetAndInject:
    """GET /api/icon-words and the ledger carried by every served page."""

    def test_get_returns_the_ledger(self) -> None:
        """GET serves the stored ledger, ids the registry lacks included."""
        ledger = {"version": 1, "icons": {"old.id": {"word": "kept", "glyph": None}}}
        _icon_ledger.save_ledger(_icon_ledger.ledger_path(), ledger)
        assert payload_of(_web_icon_words.icon_words_view(make_request())) == ledger

    def test_page_carries_the_ledger_with_script_breakouts_escaped(self) -> None:
        """Words are free text: '<' is escaped so a word cannot close the script."""
        _set("cmd.done", word="</script><b>x")
        html = _web_icon_words.inject_icon_words(
            b"<html><head><title>t</title></head></html>"
        )
        text = html.decode("utf-8")
        start = text.index(
            f'<script type="application/json" id="{_web_icon_words.SCRIPT_ID}">'
        )
        assert start < text.index("<title>")
        body = text[start:].split(">", 1)[1].split("</script>", 1)[0]
        assert "<" not in body
        assert json.loads(body)["icons"]["cmd.done"]["word"] == "</script><b>x"

    def test_page_carries_the_error_when_corrupt(self) -> None:
        """A corrupt ledger never breaks the page: it carries the error instead."""
        _icon_ledger.ledger_path().write_text("{broken", encoding="utf-8")
        html = _web_icon_words.inject_icon_words(b"<head></head>").decode("utf-8")
        body = html.split('">', 1)[1].split("</script>", 1)[0]
        assert json.loads(body)["error"] == "op_failed"

    def test_page_without_head_gets_the_script_first(self) -> None:
        """A fragment without <head> still carries the ledger."""
        html = _web_icon_words.inject_icon_words(b"<p>x</p>").decode("utf-8")
        assert html.startswith(
            f'<script type="application/json" id="{_web_icon_words.SCRIPT_ID}">'
        )
        assert html.endswith("<p>x</p>")


class TestRoutes:
    """The route table knows both endpoints; ids may contain dots."""

    def test_get_route(self) -> None:
        """GET /api/icon-words is the ledger view."""
        assert _web_routes.resolve("GET", "/api/icon-words") == (
            _web_icon_words.icon_words_view,
            (),
        )

    @pytest.mark.parametrize("method", ["POST", "PUT"])
    def test_set_route_captures_a_dotted_id(self, method: str) -> None:
        """POST and PUT /api/icon-words/job.state.waiting_input capture the id."""
        found = _web_routes.resolve(method, "/api/icon-words/job.state.waiting_input")
        assert found == (
            _web_icon_words.set_icon_word_view,
            ("job.state.waiting_input",),
        )

    @pytest.mark.parametrize("path", ["/api/icon-words/a b", "/api/icon-words/../x"])
    def test_malformed_ids_do_not_route(self, path: str) -> None:
        """Spaces or path tricks never reach the view."""
        assert _web_routes.resolve("POST", path) is None
