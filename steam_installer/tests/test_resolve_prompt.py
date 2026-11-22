"""The numbered pick prompt of a name search."""

from __future__ import annotations

import pytest

from steam_installer import resolve


def _results() -> list[resolve.SearchResult]:
    return [
        resolve.SearchResult(appid=1, name="One"),
        resolve.SearchResult(appid=2, name="Two"),
    ]


def test_prompt_confirm_returns_the_chosen_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt confirm returns the chosen result."""
    monkeypatch.setattr("builtins.input", lambda *a: "2")
    assert resolve.prompt_confirm(_results()).appid == 2


def test_prompt_confirm_reprompts_until_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt confirm reprompts until valid."""
    answers = iter(["", "banana", "9", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    assert resolve.prompt_confirm(_results()).appid == 1
    assert next(answers, None) is None


def test_prompt_confirm_lists_the_candidates_and_flags_bad_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Prompt confirm lists the candidates and flags bad answers."""
    answers = iter(["", "banana", "9", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    assert resolve.prompt_confirm(_results()).appid == 1
    out = capsys.readouterr().out
    assert "One" in out
    assert "Two" in out
    assert out.count("Invalid choice") == 3


def test_prompt_confirm_zero_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prompt confirm zero cancels."""
    monkeypatch.setattr("builtins.input", lambda *a: "0")
    with pytest.raises(resolve.ResolveError, match="Cancelled"):
        resolve.prompt_confirm(_results())


def test_prompt_confirm_rejects_empty_result_list() -> None:
    """Never guess an app: no matches must be an error, not a default pick."""
    with pytest.raises(resolve.ResolveError, match="No matches"):
        resolve.prompt_confirm([])
