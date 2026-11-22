"""Tests for the stdlib KeyValues (``.vdf`` / ``.acf``) parser."""

from __future__ import annotations

import pytest

from steam_backlog_enforcer._vdf_text import lookup, parse_vdf

TREE = {"Outer": {"Inner": {"leaf": "v"}, "flat": "s"}}


class TestParse:
    """parse_vdf builds the whole tree or raises."""

    def test_nested_blocks(self) -> None:
        """Blocks nest and empty strings survive."""
        text = '"A"\n{\n\t"b"\t\t"1"\n\t"C"\n\t{\n\t\t"d"\t""\n\t}\n}\n'
        assert parse_vdf(text) == {"A": {"b": "1", "C": {"d": ""}}}

    def test_escapes_comments_conditionals_and_bare_tokens(self) -> None:
        """Escapes, comments, conditionals and bare words parse."""
        text = (
            "// header comment\n"
            '"root" {\n'
            '  "path" "C:\\\\Games\\"x\\"\\n\\t" [$WIN32]\n'
            "  bare word // trailing\n"
            "}\n"
        )
        assert parse_vdf(text) == {"root": {"path": 'C:\\Games"x"\n\t', "bare": "word"}}

    @pytest.mark.parametrize(
        "text",
        [
            '"a" "unterminated',
            '"a" "1" }',
            '"a" { "b" "1"',
            '{ "b" "1" }',
            '"a" { "b" }',
            '"dangling"',
        ],
    )
    def test_malformed_raises(self, text: str) -> None:
        """Every malformed shape raises instead of returning part of a tree."""
        with pytest.raises(ValueError, match="malformed KeyValues"):
            parse_vdf(text)


class TestLookup:
    """lookup walks keys case-insensitively."""

    def test_case_insensitive_path(self) -> None:
        """Keys match regardless of case."""
        assert lookup(TREE, "outer", "INNER", "Leaf") == "v"

    def test_missing_key(self) -> None:
        """A missing key returns None."""
        assert lookup(TREE, "outer", "nope") is None

    def test_through_a_string(self) -> None:
        """A path through a plain string returns None."""
        assert lookup(TREE, "outer", "flat", "deeper") is None
