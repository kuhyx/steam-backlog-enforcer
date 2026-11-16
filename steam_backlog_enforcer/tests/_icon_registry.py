"""A two-icon registry the icon-word tests use instead of the real one."""

from __future__ import annotations

REGISTRY: dict[str, object] = {
    "version": 1,
    "icons": {
        "nav.dashboard": {
            "glyph": "🏠",
            "spoken": "Dashboard",
            "desc": "d",
            "words": ["home", "dashboard", "overview"],
            "alts": ["🏡", "🧭", "📟"],
        },
        "cmd.done": {
            "glyph": "🏆",
            "spoken": "Done",
            "desc": "d",
            "words": ["done", "finished", "next"],
            "alts": ["🥇", "🎉", "🏁"],
        },
    },
}
