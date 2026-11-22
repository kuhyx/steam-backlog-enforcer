"""Turning one free-form argument into a confirmed Steam app.

Four shapes have to work -- an AppID, a Steam URL, an exact title and a
partial title -- and the ambiguous cases have to fail rather than guess.
"""

import pytest

from steam_installer import appinfo, resolve, target


def _metadata(appid):
    return appinfo.AppMetadata(appid, "BeamNG.drive", "BeamNG.drive")


@pytest.fixture
def steam_knows_the_app(monkeypatch):
    monkeypatch.setattr(appinfo, "get_metadata", _metadata)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("284160", (284160, "appid")),
        ("  284160  ", (284160, "appid")),
        ("https://steamcommunity.com/app/284160/guides/", (284160, "url")),
        ("https://store.steampowered.com/app/284160/BeamNGdrive/", (284160, "url")),
        ("https://store.steampowered.com/app/284160", (284160, "url")),
        ("https://store.steampowered.com/app/284160/?snr=1_7", (284160, "url")),
        ("steamcommunity.com/app/284160/", (284160, "url")),
        ("BeamNG.drive", None),
        ("BeamNG", None),
        ("0", None),
        ("https://steamcommunity.com/id/someone/", None),
    ],
)
def test_parse_literal_recognises_appids_and_urls(text, expected):
    assert target.parse_literal(text) == expected


def test_an_appid_is_confirmed_through_steamcmd(steam_knows_the_app):
    resolved = target.resolve_target("284160", None, interactive=False)
    assert resolved.metadata.appid == 284160
    assert resolved.source == "appid"


def test_the_appid_flag_skips_detection_entirely(steam_knows_the_app):
    resolved = target.resolve_target("ignored name", 284160, interactive=False)
    assert resolved.metadata.appid == 284160
    assert resolved.source == "flag"


def test_a_url_resolves_without_searching(monkeypatch, steam_knows_the_app):
    def no_search(name):
        raise AssertionError("a URL must not trigger a search")

    monkeypatch.setattr(resolve, "search", no_search)
    resolved = target.resolve_target(
        "https://steamcommunity.com/app/284160/guides/", None, interactive=False
    )
    assert resolved.source == "url"


def test_a_single_search_hit_is_taken(monkeypatch, steam_knows_the_app):
    monkeypatch.setattr(
        resolve, "search", lambda name: [resolve.SearchResult(284160, "BeamNG.drive")]
    )
    resolved = target.resolve_target("BeamNG", None, interactive=False)
    assert resolved.metadata.appid == 284160
    assert resolved.source == "only match"


def test_an_exact_title_wins_over_a_higher_ranked_sequel(monkeypatch):
    """Steam ranks Portal 2 first for "Portal"; typing the full name must not
    install the sequel."""
    monkeypatch.setattr(
        resolve,
        "search",
        lambda name: [
            resolve.SearchResult(620, "Portal 2"),
            resolve.SearchResult(400, "Portal"),
        ],
    )
    monkeypatch.setattr(
        appinfo, "get_metadata", lambda appid: appinfo.AppMetadata(appid, "Portal", "P")
    )

    resolved = target.resolve_target("Portal", None, interactive=False)

    assert resolved.metadata.appid == 400
    assert resolved.source == "exact"


def test_an_ambiguous_name_prompts_when_interactive(monkeypatch, steam_knows_the_app):
    results = [resolve.SearchResult(1, "Witcher 3"), resolve.SearchResult(2, "Witcher")]
    monkeypatch.setattr(resolve, "search", lambda name: results)
    monkeypatch.setattr(resolve, "prompt_confirm", lambda r: r[1])

    resolved = target.resolve_target("witch", None, interactive=True)

    assert resolved.source == "picked"


def test_an_ambiguous_name_fails_closed_when_not_interactive(
    monkeypatch, steam_knows_the_app, capsys
):
    """Guessing here is how the wrong 90 GB gets downloaded."""
    monkeypatch.setattr(
        resolve,
        "search",
        lambda name: [
            resolve.SearchResult(1, "Witcher 3"),
            resolve.SearchResult(2, "Witcher 2"),
        ],
    )

    with pytest.raises(target.TargetError, match="Ambiguous"):
        target.resolve_target("witch", None, interactive=False)

    err = capsys.readouterr().err
    assert "Witcher 3" in err
    assert "Witcher 2" in err


def test_no_matches_is_an_error_not_a_default_pick(monkeypatch):
    monkeypatch.setattr(resolve, "search", lambda name: [])
    with pytest.raises(target.TargetError, match="No Steam app matches"):
        target.resolve_target("kwyjibo", None, interactive=False)


def test_search_being_unavailable_points_at_the_appid_workaround(monkeypatch):
    def boom(name):
        raise resolve.SearchUnavailable("tls blocked")

    monkeypatch.setattr(resolve, "search", boom)

    with pytest.raises(target.TargetError, match="numeric AppID"):
        target.resolve_target("BeamNG", None, interactive=False)


def test_digits_that_are_not_an_appid_fall_through_to_a_name_search(monkeypatch):
    """A game literally called "2048" exists, so digits are not unambiguous."""
    tried = []

    def metadata(appid):
        tried.append(appid)
        if appid == 2048:
            raise appinfo.AppInfoError("no such app")
        return appinfo.AppMetadata(appid, "2048", "2048")

    monkeypatch.setattr(appinfo, "get_metadata", metadata)
    monkeypatch.setattr(
        resolve, "search", lambda name: [resolve.SearchResult(999, "2048")]
    )

    resolved = target.resolve_target("2048", None, interactive=False)

    assert resolved.metadata.appid == 999
    assert tried == [2048, 999]


def test_an_unknown_appid_from_a_url_does_not_fall_through(monkeypatch):
    """A URL cannot also be a game's name, so there is nothing to fall back to."""

    def boom(appid):
        raise appinfo.AppInfoError("no such app")

    monkeypatch.setattr(appinfo, "get_metadata", boom)

    with pytest.raises(target.TargetError, match="not a known Steam app"):
        target.resolve_target(
            "https://store.steampowered.com/app/1/x/", None, interactive=False
        )


def test_no_target_at_all_is_an_error():
    with pytest.raises(target.TargetError, match="No target given"):
        target.resolve_target(None, None, interactive=False)
