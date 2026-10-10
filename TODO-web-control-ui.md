# Move every run.sh command into the React web UI

REMOVE ME AFTER FINISH

Spec agreed with the user on 2026-10-10 (grilling rounds in session
`session_01M3QPamsDnLQyQ6g4rresQf`). Contract: `DOCS-web-control-api.md` +
`web/src/api/contract.ts`.

## what
A production-quality React/TS UI that covers ALL 24 CLI commands (views,
jobs with live progress, setup wizard, daemon + server health), so nobody
has to type `./run.sh <cmd>`. The CLI stays as backend/recovery path; bare
`./run.sh` opens the UI.

## must
- Privileged ops go through the root daemon's `ctl.sock` (SO_PEERCRED);
  the web server never gets root.
- Friction enforced server/daemon-side (phrases, gaming-reset 300 s
  heartbeat countdown, unblock cap; exceptions are immediate since de76c65,
  user decision 2026-10-10). More friction, not
  less.
- must not: any way to stop/disable the enforcer (UI, CLI or socket).
  Restart only, rate-limited, after a state flush.
- Long ops: profile on scratch state, fix top hotspot each, determinate
  progress (step N/M, item, ETA) for anything >2 s.
- Stack: React 19 + React Compiler + TanStack Router/Query, newest stable,
  exact pins; tokens from `~/src/utils/unified-design-system`; keyboard
  operability per its `DOCS-operability.md`.
- `.desktop` entry opening a Chrome `--app` window (never port 9222).

## done
- Every command has a working UI control, driven in headless chromium
  against a scratch state dir, with a screenshot each; one live pass of
  status + done.
- Before/after timing table for long ops, none slower.
- vitest 100 % on `web/src`, pytest 100 % on new Python modules,
  pre-commit + dependency-freshness green.
- Daemon socket: passed in vmbox, then deployed (`sudo ./install.sh`,
  daemon restarted) and verified live.

## status
- [x] contract frozen
- [x] A: Python job runner + Progress/Prompter refactor of input() sites
      (applied to main tree, uncommitted; CLI "Type YES" → friction phrases)
- [x] B: root daemon ctl.sock + two-phase privileged ops — passed in vmbox,
      NOT deployed to host yet (needs `sudo ./install.sh` + daemon restart)
- [x] C: frontend shell + all screens against mocked backend (landed;
      contract split into contract.ts + jobContract.ts for the 250 cap;
      `npm run dev:mock` runs it against web/mock)
- [x] D: server write endpoints, auth, SSE, views, catalog; wire A+B
- [x] D2: integration fixes (arm phrase, not_found/server_stale, dev proxy,
      token reload, per-port token, job ordering/locked-vs-busy/spawn fail,
      save_credentials keeps settings)
- [x] user decided (Q16): `reset` never unblocks the store, CLI or web —
      `release_store` flag and web `_reset` wrapper removed; verified on
      scratch HOME (tests in test_main_misc* will need updating)
- [x] E: profile + optimise long ops — check ~4x (tampering re-fetch 20 in
      flight + early stop), scan −23% after the no-achievements skip cache
      warms (`_achievement_skip.py`), scan cancel 71 s → 1 s, stats −1.7 s
      (HLTB search-URL memo). Coordinator fix: skip cache only records
      Steam's explicit 400 "no stats", never timeouts/5xx (verified).
- [x] user request: "Pick my own game…" in list/done prompts (`_own_pick.py`),
      cancel any job waiting on a prompt (cancel.request marker) — verified
- [x] G: VERIFIED 2026-10-10 — scratch HOME (grid 1369, "wicher" →
      Witcher 1/2/3, scroll 0 dropped frames p95 16.8 ms, filters, pick-mode
      re-ask/back/cancel, mock mode) + vmbox guest `sbe-g` (own-pick →
      Witcher 2 assigned in a real pick job, API + browser). Screenshots
      /tmp/sbe-g/. Pick submits only via the "Pick …" button (no
      double-click assign). Owned-cache `has_stats` + records survive only
      once the daemon runs G code (H deploy). Awaiting user confirmation.
- [x] G (spec): Steam-like library browser (user spec Q21–Q26, 2026-10-10, all as
      recommended): new Library page grid of ALL owned games with cover art,
      same component replaces the own-pick text prompt (new prompt kind
      `game`; CLI keeps text search); ineligible games greyed with reason;
      art = Steam librarycache (`~/.local/share/Steam/appcache/librarycache/
      <appid>/<hash>/library_capsule.jpg`, 558 games) → server-side CDN fetch
      + disk cache (`shared.cloudflare.steamstatic.com/store_item_assets/
      steam/apps/<id>/library_600x900.jpg`, not store-blocked) → title tile;
      lazy images; fuzzy typo-tolerant search + top-8 suggestion dropdown,
      Enter/arrows, roman↔arabic numerals; card: cover, title, ach %, HLTB h,
      playtime, installed/assigned badges; sort name/recent/completion/HLTB;
      filters hide-completed/installed/pickable. BUILT 2026-10-10 (uncommitted):
      `_web_library.py`, `_web_art.py`, owned-cache `games` records,
      `ineligible_reason` + `GamePicker`/`JobPrompter.game`, web/src/library/*,
      jobs/GamePrompt.tsx, Library.tsx toggle, styles/library.css. Scratch
      verification + mock + DOCS update delegated; own-pick end-to-end runs
      in a vmbox copy of the enforcer (user, 2026-10-10: never live). DONE: grid lists all ~1369
      owned games with smooth scroll, "wicher" → Witcher 1/2/3 in suggestions,
      own-pick from the browser in a live Check-now job assigns the game.
- [ ] H: deploy DONE 2026-10-10 15:23 (`sudo install.sh` + daemon restart,
      ctl.sock live; gaming-reset arm → heartbeat → cancel verified live,
      204/410). STILL TODO: every-screen screenshot pass (real server,
      scratch HOME) + one live status + done pass.
- [x] tests: pytest 2707 pass, 100 % line+branch; vitest 523 pass, 100 %
      (React Compiler off under vitest only: its memo-cache branches are
      unreachable for coverage)
- [x] F: run.sh bare → UI (`scripts/open_ui.sh`), .desktop entry (install.sh
      `install_desktop_entry`) — opened live, WM class verified
- [x] H screenshot pass DONE 2026-10-10 (vmbox guest `sbe-g`, shots
      /tmp/sbe-h/shots/): all 24 commands driven through the UI. Fixed on the
      way (uncommitted): unhide skips like hide without Steam; enforce demo
      button was a self-link (enforce is a "screen") → runs `{demo: 1}`,
      restart sends `{demo: 0}`, mock mirrors the real catalog; enforce spec
      now `cancellable` (demo loops forever, had no Cancel); demo run crashed
      consuming the root-only restart-gap marker → demo never touches it;
      "unsupported" hint named the daemon for a server error. serve restart
      verified under systemd-run (PID + page reload); setup verified with a
      bad key only (real key not copied off the guest). Live: status UI ==
      CLI; done stays guest-only (deviation from `done`, by user rule).
      Second round: enforce dialog per preset (`enforcePreset.ts`: demo =
      user job, cancellable, no root chip; restart = root, not cancellable;
      mode field hidden); demo budget log → CONFIG_DIR (was root-only
      /var/log, EACCES); `serve` exempt from the total block (refused →
      web unit crash-looped for the whole block); gaming-reset first attempt
      = daemon refused commit 34 ms before ready_at (host/guest clock skew +
      instant retype) → commit unlocks 1 s after ready_at.
- [x] user decision 2026-10-10: keep exceptions immediate; help text, DOCS
      and mock catalog fixed.
- [x] user confirmation → tests, coverage, pre-commit, commit, deploy
      (`sudo ./install.sh` + daemon restart for the _ctl_gap fix)
- [x] 2026-10-10 test leak closed: a stale `enforce --demo` test ran the real
      demo loop on the host, read the live /proc, billed and SIGTERMed the
      game being played and shut Steam down. New autouse guard
      `tests/_no_real_effects.py`: os.kill/killpg only reach pytest and its
      own spawns, real Popen refuses Steam/kill argv, an unpatched demo tick
      fails at once, and any blocked call fails the test at teardown. Proven
      in vmbox: the OLD test now fails in 1 s with the fake game alive; with
      the tripwire removed the os.kill layer alone blocks the SIGTERM.
- [ ] F2: live verification of the finished UI
- [x] user confirmation → tests, coverage, pre-commit, commit (2026-10-10)
