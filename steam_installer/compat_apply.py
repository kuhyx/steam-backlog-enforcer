"""Run the per-game decision and, when it says so, write the mapping.

Shared by the install flow (right after the manifest is finished, while Steam
is still closed) and by `--map-installed`. The decision rules live in
:mod:`compat_decide`, the config.vdf edit in :mod:`compat_map`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from steam_installer import anticheat, appinfo, compat_decide, compat_map, proton_pkg

if TYPE_CHECKING:
    import logging
    from pathlib import Path

VALVE_PROTON = "--valve-proton"
TOOL_DIR = "compatibilitytools.d/proton-cachyos-native"


class Context:
    """What every decision in one run shares: fetched once, not per game."""

    def __init__(
        self, steam_root: Path, extra_overrides: dict[str, str] | None = None
    ) -> None:
        """Remember what every decision in this run shares."""
        self.steam_root = steam_root
        self.config = compat_map.config_path(steam_root)
        self.anticheat = anticheat.steam_ids()
        self.overrides = {**compat_decide.load_overrides(), **(extra_overrides or {})}
        self.tool_ready = compat_decide.tool_ready(
            steam_root / TOOL_DIR, proton_pkg.read_lock().version
        )

    def decide(
        self, appid: int, block: dict[str, Any], *, owned_dlc: bool
    ) -> compat_decide.Decision:
        """Decide whether *appid* maps to the native Proton."""
        facts = compat_decide.Facts(
            anticheat=self.anticheat,
            overrides=self.overrides,
            tool_ready=self.tool_ready,
        )
        return compat_decide.decide(appid, block, facts, owned_dlc=owned_dlc)


def after_install(
    steam_root: Path,
    appid: int,
    *,
    owned_dlc: bool,
    valve_proton: bool,
    logger: logging.Logger,
) -> None:
    """Map a freshly installed game, or say why it keeps Valve's default.

    Never fails the install: a game left unmapped still runs on Valve's
    Proton, exactly as before this tool knew about compat tools.
    """
    extra = {str(appid): VALVE_PROTON} if valve_proton else {}
    try:
        context = Context(steam_root, extra)
        decision = context.decide(
            appid, appinfo.fetch_app_block(appid), owned_dlc=owned_dlc
        )
        if not decision.map:
            logger.info("Compat tool: %s", decision.describe())
            return
        outcome = compat_map.map_app(context.config, appid)
    except (
        appinfo.AppInfoError,
        compat_map.CompatMapError,
        OSError,
        ValueError,
    ) as exc:
        logger.warning(
            "Compat tool not set (%s); the game stays on Valve's default.", exc
        )
        return
    report(logger, appid, outcome)


def report(logger: logging.Logger, appid: int, outcome: compat_map.Outcome) -> None:
    """Log what happened to *appid*'s compat mapping."""
    if outcome.action == "kept":
        logger.info("Compat tool for %s kept: %s", appid, outcome.detail)
    elif outcome.action == "already":
        logger.info("Compat tool for %s: already mapped to %s.", appid, compat_map.TOOL)
    else:
        logger.info("Compat tool for %s: mapped to %s.", appid, compat_map.TOOL)
