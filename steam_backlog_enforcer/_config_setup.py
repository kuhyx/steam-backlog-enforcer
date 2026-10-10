"""First-run interactive configuration.

Split out of ``config.py``: prompting a human for credentials is a different
concern from the data model those credentials live in, and only the ``setup``
command ever reaches it. The existing ``test_config_interactive_setup.py``
already treated it as its own unit.
"""

from __future__ import annotations

from dataclasses import replace
import json
import sys

from steam_backlog_enforcer import config as config_mod
from steam_backlog_enforcer._prompter import current_prompter
from steam_backlog_enforcer.config import Config


def interactive_setup() -> Config:
    """Run first-time interactive setup."""
    prompter = current_prompter()
    api_key = prompter.text("Enter your Steam Web API key")
    if not api_key:
        sys.exit(1)

    steam_id = prompter.text("Enter your Steam64 ID")
    if not steam_id:
        sys.exit(1)

    return save_credentials(api_key, steam_id)


def save_credentials(api_key: str, steam_id: str) -> Config:
    """Store *api_key* and *steam_id* in the config, owner-only.

    The non-interactive half of setup, so the web setup screen stores the
    credentials exactly the way the CLI does. Every other setting already in
    the config is kept: re-entering a key must not reset the user's choices,
    including keys this version does not model (hand-added or legacy ones).
    """
    config = replace(Config.load(), steam_api_key=api_key, steam_id=steam_id)
    # Read through the module, not an import-time binding: the path is
    # redirected in tests, and the API key lives here — it must not become
    # world-readable, nor be written to the real config during a test run.
    path = config_mod.CONFIG_FILE
    on_disk = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = on_disk | config.__dict__
    config_mod.atomic_write(path, json.dumps(merged, indent=2) + "\n")
    path.chmod(0o600)
    return config
