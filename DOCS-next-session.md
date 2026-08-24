# Next session: manual-pick rules, then finish the 250-line cap

Paste this whole file as the first prompt of a fresh session. Everything needed
is below; you should not need the previous session's transcript.

Repo: `~/steam-backlog-enforcer`. Work on `main`. HEAD is `0f25fba`.

---

## Task 1 (do this first): change the manual-pick rules

kuhy hit this and wants it changed:

```
./run.sh pick-manual 3164500      -> Error: you already have 3 manual pick(s).
./run.sh abandon-pick 495890      -> Grace period EXPIRED ... closed 3.7 day(s) ago.
./run.sh abandon-pick 618510      -> Grace period EXPIRED ... closed 3.3 day(s) ago.
```

He is stuck: three picks locked in, and the 4-day grace window closed on two of
them, so nothing can be abandoned and no new pick can be added.

**The change he asked for, verbatim:**
"allow to abandon pick at any time but reduce number of manual picks to max of 2"

So:

1. **Abandon at any time** — drop the grace-window restriction entirely.
   - `_manual_pick_lifecycle.py:73` `can_abandon_manual_pick()` currently returns
     `remaining is not None and remaining > 0`. It should return whether the pick
     exists at all, regardless of elapsed time.
   - `_manual_pick_lifecycle.py:87` `abandon_manual_pick()` has the matching
     guard; the docstring says "if still inside its grace window" — update it.
   - `MANUAL_GRACE_DAYS = 4` is declared in **two** places:
     `_actions.py:33` and `_manual_pick_lifecycle.py:40`. Decide whether the
     constant still has a purpose after this change (see "open question" below)
     and do not leave two divergent copies.
   - `manual_pick_grace_remaining()` (`_manual_pick_lifecycle.py:47`) also feeds
     `status_payload()` at line 162 as `grace_days_left`, and `run.sh status`
     prints "undoable for N more day(s)". If grace no longer gates anything,
     that display is now a lie — either drop it or restate it.

2. **Max picks 3 → 2** — `config.py:63`, `max_manual_picks: int = 3`.
   - kuhy's `~/.config/steam_backlog_enforcer/config.json` does **not** set this
     key, so it takes the default; changing the default is sufficient and no
     config migration is needed. (Verified.)

**Open question — ask kuhy before implementing, it changes the design:**
He currently has **3** picks locked and the new max is **2**. What should happen
to the existing over-cap state? Options: leave the 3 in place and simply refuse
new picks until he abandons down to 2 (least surprising); or force him to
abandon one now. `manual_pick_slots_left()` (`_actions.py:89`) returns
`max_picks - len(picks)` and will go negative — check every caller handles that,
particularly `main/picks.py:109`.

**Verify by running, not just tests** (repo CLAUDE.md requires this):
```
./run.sh status                 # read-only, safe
./run.sh abandon-pick 495890    # MUTATES STATE - confirm with kuhy first
```
`./run.sh` with **no args defaults to `done`**, which completes the current game
and reassigns. Never run it bare. `status` and `list` are the read-only ones.

---

## Task 2: finish the 250-line cap campaign (user-approved, in progress)

Three files remain. The gate is `bash scripts/check_file_length.sh --all`
(**trust the exit code only** — `| tail` and `grep -c` both report misleadingly).

```
_stats.py:       523 lines (over by 273)
scanning.py:     521 lines (over by 271)
_web_dataset.py: 436 lines (over by 186)
```

Everything else in `pre-commit run --all-files` already passes, so these three
are the only thing between the repo and a working `git push`.

### The method that works: leaf-set extraction ONLY

Extract functions that call **nothing else in their own module**. That keeps
every new import one-way, so no cycle is possible. Splitting on any other
boundary produced circular imports three separate times, and one of them broke
`./run.sh` while kuhy was using it.

Helper scripts from the last session (outside the repo, so they don't dirty git):
`/tmp/claude-1000/-home-kuhy/0f40b913-131e-43b9-b353-23de8c80a8c8/scratchpad/`
- `leaf_split.py` — run with just a module name to LIST its leaves; add
  `--new <mod> --doc "..." --names ... --apply` to perform the split.
- `missing_names.py` — reports names a module uses but never binds. Run it on
  `steam_backlog_enforcer/*.py` after every split; this catches the fallout
  immediately instead of via 30 confusing test failures.
- `retarget.py`, `add_getattr.py` — of limited value, see the warning below.

If `/tmp` has been cleared, `leaf_split.py` is ~90 lines and easy to rewrite:
parse the module, find `FunctionDef`s whose bodies call no sibling function,
move those plus a copy of the module header into a new file, and add a
top-level `from ... import (...)` back in the original.

### Traps that cost the last session hours

- **`_web_dataset` is the hard one.** Its dataclasses (`WebGame`,
  `WebStateInfo`, `WebDataset`, `PaceVsHLTB`, `DefaultSummary`, `WebDefaults`)
  are used by both the parent and the helpers, so they must go to their own
  **leaf model module** that both import — not stay in the parent. Getting this
  wrong is what broke `run.sh`.
- **`ruff-format` silently deletes bottom-of-file re-export imports** (the
  comment above them survives, so it looks intact). Put re-exports at the top,
  or serve them through a module `__getattr__`.
- **A module `__getattr__` re-export** needs: `importlib.import_module` (a call,
  so no `PLC0415`), and a `_Reexport: TypeAlias = Any` return annotation —
  `object` fails mypy at the call sites, bare `Any` fails ruff `ANN401`.
  Working examples already in the tree: `_actions.py`, `_whitelist.py`,
  `hltb.py`, `_cmd_done.py`.
- **Patch-target rule**: the target is the module whose **source file contains
  the function under test** — not where a helper is defined, not where the test
  imports from. Fix these **per file from the pytest failure list**. Six
  attempts at bulk regex retargeting had a net effect of −11 tests; per-file
  diagnosis worked every single time.
- **`@dataclass` decorators**: when copying a module header, include decorator
  lines in the boundary or you strand a bare `@dataclass` (fails with a
  confusing `'function' object has no attribute '__mro__'`).
- **Stale `.mypy_cache`** after moving symbols → `AssertionError: Cannot find
  component`. `rm -rf .mypy_cache`; it is not a real error.

### Non-negotiables

- **Use `.ci-mirror-venv/bin/python` for pytest**, not system python3 — the
  latter has mcp 2.0 against a pinned mcp<2, so `test_mcp*.py` cannot collect
  and coverage reads ~97% instead of 100%.
- Baseline to preserve: **1347 tests, 100.00% coverage**.
- **Verify with the coverage run before committing**, not `--no-cov`. Last
  session committed 3 failures after misreading a `--no-cov` run as green.
- Never `--no-verify`. Never add `# noqa` without asking.
- **The service auto-restarts from this tree** (`Restart=always`,
  `PYTHONPATH` pointed here). After any edit that could break imports, run
  `PYTHONPATH=. python3 -c "import steam_backlog_enforcer.main"` before moving
  on, and check `systemctl show steam-backlog-enforcer -p NRestarts --value`.
- **Test runs can write to real config.** Two leaks were found and sealed last
  session (`exception_audit.log`, `owned_app_ids_cache.json`), both caused by a
  path constant moving to a new module while `tests/conftest.py` kept patching
  the old one. After any split that moves a module-level path constant, md5sum
  `~/.config/steam_backlog_enforcer` before and after a full suite run.

### When the cap is clear

`git push` (13 commits are waiting, including another session's `2ad8752` for
`install.sh`). The pre-push ci-mirror runs `pre-commit --all-files` over the
whole tree, which is why the cap has to be fully clear first.

---

## Context: what the last session actually fixed (already committed, verified)

`21fe2f7` + `919ecdf` — the enforcer was launching Steam **as root**, so Steam
answered with a `zenity` modal reading "Cannot run as root user" on kuhy's
screen. Root cause: `game_install._get_real_user()` read only `SUDO_USER`/`USER`,
neither of which systemd sets, so it returned `None` and every
`geteuid() == 0 and real_user` guard fell through to running as root. It also
caused a retry storm — 1656 attempts in 30 minutes at 1.5 GB RSS. Both fixed and
verified in production (`sudo -u kuhy env DISPLAY=:0 ... steam`, every Steam
process at uid 1000, 0 retries, ~244 MB).

Do not re-litigate that fix; it is done. Tasks 1 and 2 above are what remains.
