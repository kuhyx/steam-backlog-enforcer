"""``python -m steam_backlog_enforcer.main`` entry point.

Kept as a separate module so the invocation string baked into ``run.sh`` and
the systemd unit stays byte-identical now that ``main`` is a package.
"""

from __future__ import annotations

from steam_backlog_enforcer.main import main

if __name__ == "__main__":
    main()
