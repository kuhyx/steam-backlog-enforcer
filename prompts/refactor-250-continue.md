# Session prompt: continue the 250-line cap refactor

Paste everything below the line into a fresh Claude Code session started in
`~/steam-backlog-enforcer`.

---

Continue `refactor_claude_todo.md`: get every file in this repo under 250 lines
and take pylint to a clean 10.00, without weakening either gate.

Earlier sessions landed the gate and the three hardest modules. **Re-measure
before you start** — the numbers below were true at commit `b5b4b35`.

## State at handoff

```bash
bash scripts/check_file_length.sh --all        # 39 files over the cap
.ci-mirror-venv/bin/python -m pytest steam_backlog_enforcer/tests/ -q
                                               # 1324 pass, 100.00% coverage
~/.cache/pre-commit/repo01lfw04p/py_env-python3/bin/pylint \
    --rcfile=pyproject.toml --jobs=4 steam_backlog_enforcer scripts | tail -2
                                               # 8.69/10
```

Already done (do not redo):

- **The gate is live.** `scripts/file_length/` is a vendored copy of
  `~/utils/file_length/`, wired as the `file-length` pre-commit hook. It is
  excluded from ruff/mypy/pylint and must stay byte-identical to upstream.
  `pre-commit install` has been run (it never had been — only `pre-push`).
- `main.py` → `main/` package; `_total_block`, `_playtime`, `_mcp` split.
- `pyproject.toml`: `max-module-lines = 250`.

## Decisions already made — do not re-ask

1. **All 39 files this campaign**, then pylint. Both in scope.
2. **Gate stays on**: every commit must bring the files it touches under the
   cap. `--no-verify` is banned.
3. **Coverage must stay at exactly 100%.** No pragmas, no omits.
4. **Split by responsibility, never mechanically.** See below.
5. **No private re-export shims.** Callers import from the defining module.
6. At the very end: raise pylint `--fail-under` 8.0 → **10.0** in
   `.pre-commit-config.yaml` (a deliberate deviation from
   `prompts/pylint-to-ten.md`, which says leave it — a score with no gate
   regrows exactly like file length does).

## How to split (this is the part that goes wrong)

A generic "move these top-level defs to a sibling module" extractor was tried
and **reverted**: it moved functions without the module-level names they
referenced, so the result imported fine and only failed when called —
`ruff check --select F821` found 349 undefined names.

Per file:

1. **Read it.** Name the 2-4 jobs it does; the existing `# ────` section
   banners usually mark the real seams.
2. Give each job a module whose docstring says why it is separate. Keep the
   dependency direction one-way, leaf modules (data tables, generic helpers)
   at the bottom. Pass a dependency as a parameter when that removes a cycle.
3. **Never** `module_x_1.py` / `module_x_2.py`. Extract genuinely reusable
   helpers under their own name (`_pacman.py` came out of `_total_block` this
   way and is now shared).
4. `ruff check --select F821,F401 --no-fix <files>` after **every** extraction.
   **F821 first, then autofix F401** — the reverse order deletes imports the
   moved code still needs.
5. Repoint the matching test file (below), then commit.

### Test files are the real cost

Tests build patch targets as `f"{PKG}.{name}"`, so grepping for the literal
module path finds nothing. Once a function moves, it resolves its dependencies
from its *new* module's globals, and a patch aimed at the old module silently
stops intercepting.

For each split:

```bash
# which module actually defines each patched symbol
.ci-mirror-venv/bin/python - <<'PY'
import importlib, re, pathlib
mods = {m: importlib.import_module(f"steam_backlog_enforcer.{m}") for m in (...)}
src = pathlib.Path("steam_backlog_enforcer/tests/test_X.py").read_text()
for s in sorted(set(re.findall(r'f"\{PKG\}\.(\w+)"', src))):
    print(s, [m for m, mod in mods.items() if s in vars(mod)])
PY
```

Then split the test file so each output has **one correct `PKG`**, and
**mutation-test** at least one assertion per new module — break a line in the
production module, confirm the right test fails, restore. A passing test after
a split proves nothing on its own. Watch for these forms, which a naive
find/replace misses: `patch.object(mod, "name")`, the multi-line
`patch.object(\n    mod, "name")`, and dotted `f"{PKG}.subprocess.run"`.

### Two traps that already cost time

- **ruff `--fix --unsafe-fixes` deletes autouse fixture imports** (pytest
  resolves fixtures by name, so they look unused). `conftest.py` holds them
  with an explicit `__all__` — keep it that way when adding more.
- **`conftest.py` is the filesystem safety net.** When a path constant moves
  to a new module, update the conftest patch target in the *same* edit, then
  confirm no test writes outside `tmp_path`.

## Remaining work, highest ROI first

Production (15) — the todo ranks by lines x commits/yr, so start here:

| lines | file |
|---:|:---|
| 555 | `library_hider.py` |
| 553 | `game_install.py` |
| 521 | `scanning.py` |
| 588 | `_hltb_search.py` |
| 523 | `_stats.py` |
| 436 | `_web_dataset.py` |
| 410 | `_enforce_loop.py` |
| 399 | `store_blocker.py` |
| 384 | `hltb.py` |
| 373 | `_hltb_detail.py` |
| 333 | `_cmd_done.py` |
| 298 | `_whitelist.py` |
| 282 | `_actions.py` |
| 281 | `steam_api.py` |
| 253 | `_scanning_confidence.py` |

Test files (24), largest first: `test_stats.py` 1072, `test_web_dataset.py`
620, `test_hltb_detail.py` 592, `test_store_blocker.py` 470,
`test_library_hider.py` 468, `test_hltb.py` 447, `test_scanning.py` 444, then
17 more between 255 and 417. Split these to **~200 lines, not 249** — the
pylint phase adds a docstring to every test function and would push a 249-line
file back over.

Then **pylint 8.69 → 10.00** per `prompts/pylint-to-ten.md`. ~1600 findings,
of which 1061 are `missing-function-docstring` in `tests/`. Fix
`duplicate-code` (R0801) by extracting shared test helpers, never by adding
`ignore-imports`/`ignore-signatures`. R0801 is cross-module so it is invisible
to the staged-files hook — acceptance is a **full-tree** run.

## Commands

Keep every command under ~10s; nothing over 60s.

```bash
# scoped test run for the file you just touched (~0.3s)
python3 -m pytest steam_backlog_enforcer/tests/test_<area>*.py -q --no-cov

# acceptance: use the clean venv, NOT system python3 (see below)
.ci-mirror-venv/bin/python -m pytest steam_backlog_enforcer/tests/ -q   # ~21s

# before each commit
pre-commit run --files $(git diff --cached --name-only | tr '\n' ' ')
```

**System `python3` has `mcp 2.0.0` but `requirements.txt` pins `mcp<2`**, so
`test_mcp*.py` fails to collect and coverage reports ~97%. That is a local
environment artifact, not a regression — use `.ci-mirror-venv/bin/python` for
anything coverage-related. Do not "fix" it by moving the pin.

Long jobs (`scripts/ci_mirror.sh`, full-suite runs) go in the background with
`run_in_background: true` rather than a long foreground timeout.

## Done condition

- `bash scripts/check_file_length.sh --all` → exit 0, and the todo's literal
  `bash ~/utils/scripts/check_file_length.sh --all` → exit 0 (running both
  catches drift between the vendored copy and upstream).
- `.ci-mirror-venv/bin/python -m pytest steam_backlog_enforcer/tests/ -q` →
  green at exactly 100%.
- Full-tree pylint → **10.00/10**, with `--fail-under=10.0` committed.
- `pre-commit run --all-files` passes.
- A staged 251-line file still makes `git commit` fail.
- `./run.sh` runs and its output is unchanged. To prove a refactor is
  behaviour-preserving despite live Steam state changing under you, compare
  against a worktree at HEAD rather than an older captured baseline:
  `git worktree add --detach /tmp/wt HEAD` and diff the two runs.

## Verify

Run the enforcer entry point, show the output, and confirm with the user.
**Do NOT restart the systemd unit or Steam** — a real total-block/manual-pick
lock may be active on this machine; ask first.
