"""Command registry and argv resolution.

Split out of :mod:`steam_backlog_enforcer.main` to keep every module inside the
250-line cap; the tables here are what ``main()`` dispatches on.
"""

from __future__ import annotations

import difflib

from steam_backlog_enforcer.game_install import _echo


def _make_all_commands(
    commands: dict[str, tuple[str, object]],
    extra: dict[str, str],
) -> dict[str, str]:
    """Merge the dispatchable commands with the raw-argv ones for help/lookup."""
    return {name: desc for name, (desc, _) in commands.items()} | extra


def _resolve_command(raw: str, all_commands: dict[str, str]) -> str | None:
    """Map a raw argv[1] onto a known command name.

    Subcommands are bare words, but the CLI does use flags elsewhere
    (``add-exception --reason``), so ``--abandon-pick`` is the natural
    muscle-memory guess. Leading dashes carry no meaning in this slot,
    so they are simply stripped rather than rejected.

    Parameters:
    raw (str): The first CLI argument, exactly as the user typed it.

    Returns:
    str | None: The canonical command name, or None if unrecognised.
    """
    if raw in all_commands:
        return raw
    if raw.startswith("-"):
        stripped = raw.lstrip("-")
        if stripped in all_commands:
            return stripped
    return None


def _print_usage(all_commands: dict[str, str], unknown: str | None = None) -> None:
    """Print the command list, optionally explaining a bad command.

    Parameters:
    unknown (str | None): The unrecognised argument to report. When None
        (the no-arguments case) only the usage block is printed.
    """
    if unknown is not None:
        _echo(f"Unknown command: {unknown}")
        close = difflib.get_close_matches(
            unknown.lstrip("-"), all_commands, n=1, cutoff=0.6
        )
        if close:
            _echo(f"Did you mean '{close[0]}'?")
        _echo("")
    _echo("Steam Backlog Enforcer\n")
    _echo("Usage: python -m steam_backlog_enforcer.main <command> [args]\n")
    _echo("Commands:")
    for name, desc in all_commands.items():
        _echo(f"  {name:<14s}  {desc}")
