"""First-run interactive configuration.

Split out of ``config.py``: prompting a human for credentials is a different
concern from the data model those credentials live in, and only the ``setup``
command ever reaches it. The existing ``test_config_interactive_setup.py``
already treated it as its own unit.
"""

from __future__ import annotations

import sys

from steam_backlog_enforcer import config as config_mod
from steam_backlog_enforcer.config import Config


def interactive_setup() -> Config:
    """Run first-time interactive setup."""
    api_key = input("Enter your Steam Web API key: ").strip()
    if not api_key:
        sys.exit(1)

    steam_id = input("Enter your Steam64 ID: ").strip()
    if not steam_id:
        sys.exit(1)

    config = Config(steam_api_key=api_key, steam_id=steam_id)
    config.save()
    # Read through the module, not an import-time binding: the path is
    # redirected in tests, and the API key lives here — it must not become
    # world-readable, nor be written to the real config during a test run.
    config_mod.CONFIG_FILE.chmod(0o600)
    return config
