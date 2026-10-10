"""``python -m steam_backlog_enforcer.jobs run <job_dir>``: run one web job.

Spawned by the web server (:func:`steam_backlog_enforcer.jobs._store.create_job`);
it can also be run by hand on a prepared job dir to debug a job.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from steam_backlog_enforcer.jobs._runner import run_job


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the job; return its exit code."""
    parser = argparse.ArgumentParser(prog="python -m steam_backlog_enforcer.jobs")
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", help="run the job in JOB_DIR")
    run.add_argument("job_dir", type=Path)
    args = parser.parse_args(argv)
    return run_job(args.job_dir)


if __name__ == "__main__":
    sys.exit(main())
