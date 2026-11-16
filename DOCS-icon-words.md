# Icon words API

Part of the web control API ([DOCS-web-control-api.md](DOCS-web-control-api.md)).

## `/api/icon-words`

`GET /api/icon-words` → `IconLedger`; `POST` or `PUT /api/icon-words/{icon_id}` with `{word?, glyph?}` → `IconLedger` (200). Writes need Host, Origin and `X-SBE-Token` like every non-GET. TS mirror: `web/src/api/iconWordsContract.ts`.

- **Ledger** `web/src/ui/icon_words.json` (a repo file the user commits; `SBE_ICON_WORDS` overrides the path): `{"version":1,"icons":{"<id>":{"word":"<text>"|null,"glyph":"<emoji>"|null}}}`. Absent id = unanswered; no `word` key = only a glyph chosen; `word: null` = skipped (no label); `glyph: null` = default. The server reads it per request and never builds from it (`_web_build` ignores it); writes go to a sibling temp file, then rename.
- **Registry** `web/src/icons/registry.json`: id → default glyph, spoken name, description, 3 suggested words, 3 alternative glyphs (`registry.ts` types it).
- **`word`**: any text; casing kept, whitespace runs collapsed; 1–40 characters, no control characters, else `invalid_params`. `null` skips. **`glyph`**: the default or one of the icon's 3 alternatives (the default is stored as `null`), else `invalid_params`. Unknown id → `not_found`; empty body or unknown key → `invalid_params`.
- Every served `.html` page carries the ledger as `<script type="application/json" id="sbe-icon-words">` (`<` escaped), so a pick shows on the next page load.
- **Corrupt ledger** (bad JSON or schema): copied to `<ledger>.corrupt` (an older copy is never overwritten) and left in place; every read and write answers `op_failed` (500) naming the copy until someone fixes it. Pages then carry that error body and draw no words.
- UI: a word is drawn right of its icon in sentence case (`web/src/icons/textCase.ts` holds the acronym list); the `/words` picker (palette → Icon words) sets words and glyphs; `localStorage["sbe-icon-words-hidden"] = "1"` hides all words.
