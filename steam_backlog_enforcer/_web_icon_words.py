"""``/api/icon-words``: the words the user puts next to the UI's icons.

The UI is text-free except for these: every icon has a registry entry
(``web/src/icons/registry.json``: default glyph, 3 suggested words, 3
alternative glyphs) and the user picks a word and optionally a glyph for each
on the ``/words`` page. Picks land in the ledger (:mod:`._icon_ledger`) and
every served page carries the ledger as a JSON ``<script>``, so a pick shows
on the next page load without a rebuild.

Manual words are always accepted, whatever they say: casing is kept,
whitespace runs collapse to one space, and only empty, over-40-character or
control-character text is refused. A glyph must be the icon's default or one
of its three registered alternatives.
"""

from __future__ import annotations

from http import HTTPStatus
import json
import logging
from pathlib import Path
import re
import threading
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer import _icon_ledger
from steam_backlog_enforcer._web_errors import ApiError, not_found
from steam_backlog_enforcer._web_io import Reply, ok

if TYPE_CHECKING:
    from steam_backlog_enforcer._web_io import Request

logger = logging.getLogger(__name__)

REGISTRY_FILE: Final = (
    Path(__file__).resolve().parent.parent / "web" / "src" / "icons" / "registry.json"
)
# The <script id> the UI reads at boot (ICON_WORDS_SCRIPT in iconWordsContract.ts).
SCRIPT_ID: Final = "sbe-icon-words"
MAX_WORD: Final = 40
# The same classes as web/src/icons/wordRules.ts, spelled out so Python's
# wider ``\s`` (it counts \x1c-\x1f as space) cannot make the two disagree.
_SPACE: Final = re.compile(r"[\t\n\v\f\r \u00a0\u2000-\u200a\u2028\u2029\u202f\u3000]+")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_HEAD_TAG: Final = re.compile(rb"<head[^>]*>", re.IGNORECASE)
_BODY_KEYS: Final = frozenset({"word", "glyph"})
# One writer at a time: the server is threaded and a save is read-modify-write.
_WRITE_LOCK = threading.Lock()


def _failed(message: str) -> ApiError:
    """A loud 500: the ledger or registry cannot be used as it is."""
    return ApiError(message, code="op_failed", status=HTTPStatus.INTERNAL_SERVER_ERROR)


def _load() -> _icon_ledger.Ledger:
    """The current ledger; a corrupt one is logged and refused."""
    try:
        return _icon_ledger.load_ledger(_icon_ledger.ledger_path())
    except _icon_ledger.LedgerCorruptError as exc:
        failure = exc
    # Logged outside the handler: the message is the whole story, no traceback.
    logger.error("%s", failure)
    raise _failed(str(failure))


def load_registry() -> dict[str, dict[str, Any]]:
    """Every registered icon by id (its default glyph and alternatives)."""
    try:
        return json.loads(REGISTRY_FILE.read_text("utf-8"))["icons"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"The icon registry {REGISTRY_FILE} is unreadable: {exc}."
        raise _failed(msg) from None


def normalize_word(raw: object) -> str:
    """The word to store for *raw*: collapsed whitespace, casing kept.

    Raises:
        ApiError: ``invalid_params`` for non-text, empty, over-long or
            control-character input.
    """
    if not isinstance(raw, str):
        msg = "word must be text, or null to skip."
        raise ApiError(msg, code="invalid_params")
    word = _SPACE.sub(" ", raw).strip()
    if not word:
        msg = "word is empty; send null to skip this icon instead."
        raise ApiError(msg, code="invalid_params")
    if len(word) > MAX_WORD:
        msg = f"word is {len(word)} characters; at most {MAX_WORD} fit next to an icon."
        raise ApiError(msg, code="invalid_params")
    if _CONTROL.search(word):
        msg = "word holds a control character."
        raise ApiError(msg, code="invalid_params")
    return word


def _glyph(raw: object, entry: dict[str, Any]) -> str | None:
    """The glyph to store: null for the default, else a registered alternative.

    Raises:
        ApiError: ``invalid_params`` for anything else.
    """
    if raw is None or raw == entry["glyph"]:
        return None
    if isinstance(raw, str) and raw in entry["alts"]:
        return raw
    allowed = " ".join(entry["alts"])
    msg = f"glyph must be the default {entry['glyph']} or one of {allowed}."
    raise ApiError(msg, code="invalid_params")


def _update(body: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """The validated changes in *body* (``word`` and/or ``glyph``)."""
    unknown = set(body) - _BODY_KEYS
    if unknown or not body:
        msg = (
            "Send word (text, or null to skip) and/or glyph (an alternative, or null)."
        )
        raise ApiError(msg, code="invalid_params")
    out: dict[str, Any] = {}
    if "word" in body:
        out["word"] = None if body["word"] is None else normalize_word(body["word"])
    if "glyph" in body:
        out["glyph"] = _glyph(body["glyph"], entry)
    return out


def icon_words_view(_request: Request) -> Reply:
    """``GET /api/icon-words`` — the whole ledger."""
    return ok(_load())


def set_icon_word_view(request: Request) -> Reply:
    """``POST|PUT /api/icon-words/{icon}`` — save a word, skip or glyph."""
    (icon,) = request.args
    entry = load_registry().get(icon)
    if entry is None:
        msg = f"No icon {icon!r} is registered."
        raise not_found(msg)
    changes = _update(request.body, entry)
    with _WRITE_LOCK:
        ledger = _load()
        saved = ledger["icons"].setdefault(icon, {})
        saved.update(changes)
        saved.setdefault("glyph", None)
        _icon_ledger.save_ledger(_icon_ledger.ledger_path(), ledger)
    return ok(ledger)


def inject_icon_words(html: bytes) -> bytes:
    """Insert the ledger as ``<script type="application/json">`` after ``<head>``.

    A corrupt ledger never breaks the page: the script then carries the
    error body, which the UI reports. ``<`` is escaped, so no word can close
    the script element early.
    """
    try:
        payload: object = _load()
    except ApiError as exc:
        payload = exc.body()
    text = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    tag = f'<script type="application/json" id="{SCRIPT_ID}">{text}</script>'.encode()
    match = _HEAD_TAG.search(html)
    if match is None:
        return tag + html
    return html[: match.end()] + tag + html[match.end() :]
