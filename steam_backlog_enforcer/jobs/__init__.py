"""Web jobs: CLI commands run as detached subprocesses with live events.

A job is a directory under ``~/.local/state/steam-backlog-enforcer/jobs/``
(see ``DOCS-web-control-api.md``, "Jobs"). The web server creates it and
spawns ``python -m steam_backlog_enforcer.jobs run <job_dir>``; from then on
the two only share files, so a job outlives page reloads and server restarts.

- :mod:`._store` — create, prune and spawn jobs; the one-mutating-job lock.
- :mod:`._view` — read jobs and their events back for the API.
- :mod:`._control` — answer a prompt, cancel a job.
- :mod:`._runner` — what runs inside the subprocess.
- :mod:`._registry` — which command runs as which job.
"""
