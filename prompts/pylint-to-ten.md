# Session prompt: take pylint from 8.65 to 10.00

Paste everything below the line into a fresh Claude Code session started in
`~/steam-backlog-enforcer`.

---

Take this repo's pylint score from **8.65/10 to a clean 10.00/10**, without
weakening the linter.

## Why

The pre-commit pylint hook runs with `--fail-under=8.0`, so at 8.65 the repo
passes its gate while carrying ~1600 findings. The threshold is hiding the
debt rather than measuring it. The same job was done in `~/utils/crdt-sync`
on 2026-08-21 (8.58 -> 10.00); this repo has the identical shape of problem,
only larger.

Measured on this machine, 2026-08-21, with
`~/.cache/pre-commit/repo01lfw04p/py_env-python3/bin/pylint --rcfile=pyproject.toml steam_backlog_enforcer scripts`:

| category | count |
|---|---|
| missing-function-docstring | 1061 |
| use-implicit-booleaness-not-comparison-to-zero | 121 |
| missing-class-docstring | 97 |
| duplicate-code | 66 |
| use-implicit-booleaness-not-comparison | 60 |
| redefined-outer-name | 42 |
| protected-access | 38 |
| import-outside-toplevel | 20 |

**All 1158 missing-docstring findings are in `steam_backlog_enforcer/tests/`.**
That is ~72% of the total and the single highest-leverage fix. There are 150
test files.

Re-measure before you start and again at the end. The first run guards
against the situation having changed; the second is the acceptance check.

## Scope

**In scope**
1. Every pylint finding under `steam_backlog_enforcer/` and `scripts/`.
2. Test docstrings — the bulk of the work.

**Out of scope — do not touch**
- `--fail-under` in `.pre-commit-config.yaml`. Do NOT raise it to hide a
  shortfall, and do NOT lower it. Leave it at 8.0; the score is what moves.
- `pyproject.toml`'s `[tool.pylint.messages_control] disable` list. Adding a
  check to it is the failure mode this task exists to avoid.
- Anything under `node_modules/`, `web/`, or `*.egg-info/`.

## The rule that decides the approach

**Fix the underlying issue; do not suppress it.** The repo blocks `noqa` and
`type: ignore` outright via a pre-commit hook. Inline `# pylint: disable=` is
permitted ONLY where the finding is a genuine false positive, and then it
must be:
- scoped to the narrowest unit (prefer `disable-next` on the exact line over
  a file-level disable),
- placed on the line that actually triggers it (verify — a `disable-next`
  one line off silently does nothing and pylint reports
  `useless-suppression`),
- accompanied by a comment saying WHY the check is wrong here.

Ask before adding any suppression that is not clearly a false positive.

## What worked in crdt-sync (copy this)

Writing 277 test docstrings by hand is slow and error-prone. Script the
first draft, then review every one:

1. Parse each test file with `ast`, find every `ClassDef`/`FunctionDef` whose
   name starts with `test_`/`Test` and has no docstring.
2. Derive prose from the identifier — these test names are already sentences.
3. **Insert at the anchor, not the first body statement.** If the first
   statement is decorated (`@staticmethod`, `@pytest.mark...`), inserting at
   its `lineno` puts the docstring BETWEEN the decorator and its `def` and
   produces a syntax error. Anchor to `min(lineno, *[d.lineno for d in
   decorator_list])`.
4. Back the test tree up first (`cp -a`), run the suite immediately after,
   and `ast.parse` every touched file before trusting it.

A docstring that merely restates the test name adds nothing — after the
generated pass, go back and improve the ones where the assertion says
something the name does not.

## Also expect

- `use-implicit-booleaness-*` (181 total): `assert not x` for `assert x == {}`
  / `== []` / `== 0` / `== ""`. Mechanical, but check each — in a test, the
  explicit form sometimes asserts the TYPE too, which is worth keeping.
- `redefined-outer-name` (42): pytest fixture idiom. Usually a rename.
- `protected-access` (38): if the private member IS the thing under test,
  that is a legitimate scoped disable with a reason.
- `duplicate-code` (66): look for near-copy fakes/helpers across test
  modules. In crdt-sync two duplicated in-memory fakes merged into one class
  in `conftest.py` — that is the sanctioned home (a non-`test_*.py` module in
  a tests dir can trip the `name-tests-test` hook). Watch coverage when
  merging: the union class must still exercise every branch.

## Gates

- `python -m pytest -q --ignore=steam_backlog_enforcer/tests/test_mcp.py`
  — **1288 passing** is the baseline (measured 2026-08-21, ~63s). That count
  must hold.

  **Read this before you think you broke something:** a plain
  `python -m pytest -q` currently fails at COLLECTION with
  `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. This is
  pre-existing and NOT yours to fix. `pyproject.toml` declares `mcp` as an
  optional extra (`mcp = ["mcp>=1.9,<2"]`) served by a dedicated venv via
  `scripts/setup_mcp.sh`; the system interpreter has `mcp 2.0.0`, and the 2.x
  line removed `mcp.server.fastmcp`. Ignore that one module, do not
  "fix" the import, and do not touch the pin — mention it in your report and
  move on.

  Because that module is skipped, coverage reads **97.32%**, not 100%. Do not
  chase the missing 2.68% and do not let a coverage gate mislead you into
  thinking your change caused it. What matters is that the number does not
  get WORSE.
- `pre-commit run --files <changed>` — must pass, including the noqa blocker.
- `ruff format` will reformat what you touch; re-run the suite after it, and
  do not let it reformat files this task never touched.

## Done means

1. `pylint --rcfile=pyproject.toml steam_backlog_enforcer scripts` reports
   **10.00/10**.
2. `--fail-under` is still 8.0 and the `disable` list is unchanged.
3. 1288 tests still passing (with `test_mcp.py` ignored, as above) and
   coverage no worse than the 97.32% baseline.
4. Every suppression you added is listed in the final report with its
   justification. If you could not reach 10.00 without a suppression the user
   would not accept, say so and report the real number instead.
