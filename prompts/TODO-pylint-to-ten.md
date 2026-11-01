# Take pylint from 9.95 to 10.00 and raise the gate

## what
Docstrings, booleaness and test duplicates are done (8.65 -> 9.95, measured
2026-11-01). About 45 findings remain in `steam_backlog_enforcer/`, all in
live-enforcer code. Fix them without changing behaviour or adding suppressions
or `[tool.pylint.messages_control] disable` entries, then raise
`--fail-under` in `.pre-commit-config.yaml` from 8.0 to 10.0.

Remaining, by check (file:line):
- broad-exception-caught: `_ctl_server.py:168,187`, `jobs/_runner.py:208,211`,
  `_leisure_kill.py:143`, `_shadow.py:123`, `_web_server.py:103`. These are
  fail-safe handlers; narrowing them changes enforcement behaviour. Needs a
  decision from kuhy: narrow, or a scoped disable with a reason.
- too-many-locals: `_hltb_confidence.py:110`, `_hltb_detail.py:144`,
  `_hltb_search.py:149`, `jobs/_runner.py:136`, `_leisure_kill.py:149`,
  `scanning.py:76`, `_stats_gathering.py:44`, `_stats.py:122`.
- too-many-instance-attributes: `config.py:85,154`, `_playtime_record.py:20`,
  `_playtime_state.py:78`, `_web_models.py:16`. Persisted state shapes; needs
  a decision (raise `max-attributes`, or restructure the stored schema).
- consider-using-with: `_ctl_server.py:154`, `_fast_install.py:152`,
  `jobs/_spawn.py:133`.
- redefined-outer-name: `library_hider.py:71,164`.
- chained-comparison: `_hltb_types.py:146`, `_steam_models.py:50`.
- useless-return: `_fast_install_progress.py:106`, `_web_sse.py:91`.
- misc: `_web_routes.py:87` no-member, `_hltb_matching.py:187`
  unsubscriptable-object, `_leetcode_ledger.py:47` unexpected-keyword-arg,
  `_game_names.py:72` useless/suppressed disable.

## done
```bash
.ci-mirror-venv/bin/python -m pylint --rcfile=pyproject.toml --jobs=4 \
    steam_backlog_enforcer | tail -2   # rated at 10.00/10
grep -n 'fail-under=10.0' .pre-commit-config.yaml
```
`scripts/file_length/` is vendored and excluded from the hook; leave it.

## verify
The full suite (`.ci-mirror-venv/bin/python -m pytest steam_backlog_enforcer/tests/ -q`,
about 25 min under `capped.sh`, so split it per file group) stays green at
100% coverage. Run `./run.sh <read-only command>` before and after. Do not
restart the systemd unit or Steam while a game runs.

## read first
- `CLAUDE.md` (commands, coverage rule)

REMOVE ME AFTER FINISH
