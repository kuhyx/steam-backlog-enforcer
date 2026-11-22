"""Command-line argument definitions for the installer."""

from __future__ import annotations

import argparse

from kuhy_credit import credit_line

from steam_installer import depotdl, map_installed


def build_parser() -> argparse.ArgumentParser:
    """Build the installer's argument parser."""
    parser = argparse.ArgumentParser(
        description="Download an owned Steam game fast, then make Steam recognize it.",
        # kuhy's shared credit line (kuhy_credit, kuhyx/utils).
        epilog=credit_line(),
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="TARGET",
        help=(
            "AppID (284160), a Steam URL "
            "(https://steamcommunity.com/app/284160/guides/), or a game name "
            "(BeamNG.drive, or just BeamNG)"
        ),
    )
    parser.add_argument(
        "--appid", type=int, default=None, help="Steam AppID (skips detection)"
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Steam account username (default: $STEAM_USERNAME, then the saved one)",
    )
    parser.add_argument(
        "--language", default=None, help="Language depot to fetch (default: prompts)"
    )
    parser.add_argument(
        "--max-downloads", type=int, default=depotdl.DEFAULT_MAX_DOWNLOADS
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Assume yes for every prompt. Ambiguous names still fail rather than guess."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the target and report what would happen. Changes nothing.",
    )
    parser.add_argument(
        "--repair-ghosts",
        action="store_true",
        help=(
            "Scan every library for the fake 'installed' manifests anonymous "
            "steamcmd leaves behind, and clear them away."
        ),
    )
    map_installed.add_arguments(parser)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show on the console everything that goes to the run log.",
    )
    return parser
