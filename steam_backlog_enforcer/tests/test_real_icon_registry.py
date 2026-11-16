"""The shipped icon registry and the user's ledger against the server's rules."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from steam_backlog_enforcer import _web_icon_words

LEDGER_FILE = (
    Path(_web_icon_words.__file__).resolve().parent.parent
    / "web"
    / "src"
    / "ui"
    / "icon_words.json"
)
# The same shape the route accepts for ``/api/icon-words/{icon}``.
ICON_ID = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
VARIATION_SELECTOR = "️"


def _registry() -> dict[str, dict[str, Any]]:
    return _web_icon_words.load_registry()


def _look(glyph: str) -> str:
    """The glyph without its emoji variation selector."""
    return glyph.replace(VARIATION_SELECTOR, "")


def test_every_registered_id_fits_the_route() -> None:
    """A registered id the route cannot match could never be saved."""
    registry = _registry()
    assert len(registry) > 45
    assert [i for i in registry if not ICON_ID.fullmatch(i)] == []


def test_every_entry_is_complete() -> None:
    """Each icon has a description, 3 one-word suggestions and 3 alternatives."""
    for icon, entry in _registry().items():
        looks = {_look(entry["glyph"]), *(_look(a) for a in entry["alts"])}
        assert entry["spoken"], icon
        assert len(entry["desc"]) > 20, icon
        assert len({w.lower() for w in entry["words"]}) == 3, icon
        assert all(re.fullmatch(r"\S+", w) for w in entry["words"]), icon
        assert len(entry["alts"]) == 3, icon
        assert len(looks) == 4, icon


def test_the_users_ledger_only_names_registered_icons() -> None:
    """Every ledger answer belongs to an icon, and a chosen glyph is one of its own."""
    registry = _registry()
    icons = json.loads(LEDGER_FILE.read_text("utf-8"))["icons"]
    assert [i for i in icons if i not in registry] == []
    for icon, choice in icons.items():
        glyph = choice.get("glyph")
        assert glyph is None or glyph in registry[icon]["alts"], icon
