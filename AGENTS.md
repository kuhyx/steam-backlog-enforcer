do NOT run tests unless specifically instructed to do so or before committing
If tests fail on the same issue twice in a row, STOP and ask the user how to proceed instead of continuing to fix and retry.
ALWAYS confirm that the feature you add / bug you fixed behaves as it should by running the program after your changes (not tests!) and inspecting output comparing it with what user wanted, after confirming by yourself ask user if the program behaves as they intended
After running tests fix all coverage gaps and issues, do not ignore unless specifically instructed to do so

@/home/kuhy/.claude/rules/typescript-5-es2022.instructions.md

# Steam Backlog Enforcer Notes

- Fixed in commit 8b7bdb6: conftest.py safety net redirects all filesystem paths (STEAMAPPS_PATH, CONFIG_DIR, STATE_FILE, etc.) to tmp_path. Tests are safe to run without asking about state.json first.
- The pre-commit `pytest-coverage` hook is currently broken (measures all of python_pkg at 100%, not just the changed subpackage). There's an in-progress fix via `scripts/pytest_changed_packages.py` + `.pre-commit-config.yaml` change that still needs lint fixes.
- Clearing `hltb_cache.json` alone is not enough for `run.sh`/`done` reassignment: `snapshot.json` also stores `completionist_hours`, and stale snapshot values can still drive reassignment decisions unless refreshed.
- After fixing Steam Backlog Enforcer logic, always run a live verification pass with `python_pkg/steam_backlog_enforcer/run.sh` (or equivalent command) before declaring the fix done.
- cmd_done completion path can pick next game from snapshot-only hours; keep it aligned with HLTB cache/refresh before pick_next_game to avoid prologue-derived stale times (e.g., A Space 0.56h while cache has ~20h).
- HLTB renames games (e.g., "Needy Streamer Overload" → "NEEDY GIRL OVERDOSE"). The old name lives in `game_alias`. Both `game_name` and `game_alias` must be checked when matching — fixed in `_pick_best_hltb_entry`.
- **ALWAYS clear HLTB cache and re-run `run.sh` after changing the HLTB picking/matching algorithm.** Delete `~/.config/steam_backlog_enforcer/hltb_cache.json` (entire file, not just one entry) so all games get re-matched with the new logic. Then run `./run.sh` to verify correct results. Stale cache entries from the old algorithm will persist and hide bugs otherwise.
