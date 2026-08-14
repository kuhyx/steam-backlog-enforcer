# Refactor TODO — enforce the 250-line file cap

> **This file is a ready-to-use prompt.** Paste it to Claude, or open this repo
> and say "do refactor_claude_todo". It is self-contained: everything needed to
> execute is below. Generated 2026-08-14 from a measured survey of every repo.

## Goal

Every file in this repo must be **at most 250 lines** — source, tests, and
prose (`.md`/`.txt`/`.rst`/`.tex`) alike — and must **stay** that way forever,
enforced by a gate that fails the commit, not by a note anyone can ignore.

Why: a file that cannot be read in one piece forces re-reads and partial edits,
which is the single largest avoidable cost in an LLM-assisted workflow. Aim by
churn, not size alone — refactoring pays where code is read and changed often
(Fowler, *refactoring economic benefit*).

## Scope in this repo

- **55 files** currently exceed 250 lines (of 113 eligible files).
- **24,887 lines** sit in violation; longest file is **1076 lines**.

Exempt (do NOT split these):
- generated files — `*.g.dart`, `*.freezed.dart`, `*.gr.dart`, `**/l10n/generated/**`,
  anything with a `GENERATED` header
- markup — `.html`, `.css`, `.scss`
- data files — `.json`, `.yaml`, `.csv`, wordlists and other data-ish `.txt`
  (mean line length under 25 chars)

## Violations, highest ROI first

ROI = lines x commits in the last year. Work top-down; a long file nobody edits
has near-zero payoff and should not be first.

| lines | commits/yr | kind | file |
|------:|-----------:|:-----|:-----|
| 1076 | 26 | code | `steam_backlog_enforcer/main.py` |
| 553 | 18 | code | `steam_backlog_enforcer/game_install.py` |
| 555 | 13 | code | `steam_backlog_enforcer/library_hider.py` |
| 521 | 13 | code | `steam_backlog_enforcer/scanning.py` |
| 384 | 16 | code | `steam_backlog_enforcer/hltb.py` |
| 447 | 12 | code | `steam_backlog_enforcer/tests/test_hltb.py` |
| 410 | 12 | code | `steam_backlog_enforcer/_enforce_loop.py` |
| 444 | 11 | code | `steam_backlog_enforcer/tests/test_scanning.py` |
| 476 | 10 | code | `steam_backlog_enforcer/tests/test_main_part2.py` |
| 1072 | 4 | code | `steam_backlog_enforcer/tests/test_stats.py` |
| 592 | 7 | code | `steam_backlog_enforcer/tests/test_hltb_detail.py` |
| 393 | 10 | code | `steam_backlog_enforcer/tests/test_enforce_loop.py` |
| 491 | 7 | code | `steam_backlog_enforcer/tests/test_main.py` |
| 333 | 10 | code | `steam_backlog_enforcer/_cmd_done.py` |
| 409 | 8 | code | `steam_backlog_enforcer/tests/test_hltb_part2.py` |

_(40 further files over 250 lines not listed — re-run the survey for the full set.)_

## How to split

- **Python** — extract cohesive helpers into sibling modules; keep the public
  API and imports stable.
- **Shell** — split into `lib/*.sh` sourced by a thin entry script. Keep
  `set -euo pipefail` in each.
- **Dart / TypeScript** — extract widgets/components into their own files.
- **Tests** — split by test-group into sibling files
  (`foo.test.ts` -> `foo.parsing.test.ts`, `foo.render.test.ts`). Coverage must
  not drop.
- **Docs** — split into topic files under `docs/` with an index. For an
  oversized `CLAUDE.md`, move detail into referenced docs so the
  always-loaded part shrinks.

**Do not** game the cap: no one-lining, no deleting tests, no moving code into
an exempt extension, no `# noqa`-style suppressions.

## Make it permanent (required — this is the point)

A refactor without a gate silently regrows. Before this task is done:

1. Wire the shared gate `~/utils/scripts/check_file_length.sh` into this repo's
   `.pre-commit-config.yaml` as a local hook. If the repo has no pre-commit
   config, add a minimal one.
2. The hook checks **files in the commit** (not the whole tree), so unrelated
   commits never break, and it **fails** — exit 1, not a warning.
3. No baseline file and no allowlist. Those are suppressions.
4. If this repo has CI (`.github/workflows`), add the same check there so it
   also fails on push.

## Done condition

- `bash ~/utils/scripts/check_file_length.sh --all` from this repo root exits 0.
- The repo's own test suite and coverage bar are still green.
- `pre-commit run --files <changed files>` passes.
- A deliberately over-250-line test file, staged, makes `git commit` **fail**.
- For a deployed daemon/app: the entry point still actually runs.

## Verify

Run the suite, then run the enforcer entry point. Do NOT restart the systemd unit or Steam while a game is running — ask first.
