"""Steam AppIDs that must never be uninstalled.

Runtimes and compatibility tools, not games: removing one silently breaks
every Proton title. Split out of :mod:`steam_backlog_enforcer.game_install`
to keep that module under the 250-line cap; this is data, not logic.
"""

from __future__ import annotations

PROTECTED_APP_IDS = {
    # Steam runtimes and tooling (never uninstall these)
    228980,  # Steamworks Common Redistributables
    1070560,  # Steam Linux Runtime 1.0 (scout)
    1391110,  # Steam Linux Runtime 2.0 (soldier)
    1628350,  # Steam Linux Runtime 3.0 (sniper)
    4183110,  # Steam Linux Runtime 4.0
    4185400,  # Steam Linux Runtime 4.0 - Arm64
    961940,  # Steam Linux Runtime (legacy)
    4690330,  # Legacy Steam Runtime
    613220,  # Steam 360 Video Player
    250820,  # SteamVR
    1007,  # Steamworks SDK Redist
    # Proton versions (never uninstall these)
    858280,  # Proton 3.7 (Beta)
    930400,  # Proton 3.16 (Beta)
    1054830,  # Proton 4.2
    1113280,  # Proton 4.11
    1245040,  # Proton 5.0
    1420170,  # Proton 5.13
    1580130,  # Proton 6.3
    1887720,  # Proton 7.0
    2230260,  # Proton 7.0 (alt)
    2348590,  # Proton 8.0
    2805730,  # Proton 9.0
    3201940,  # Proton 9.0 (alt)
    3658110,  # Proton 10.0
    4628710,  # Proton 11.0
    4628740,  # Proton 11.0 (ARM64)
    2180100,  # Proton Hotfix
    1493710,  # Proton Experimental
    1161040,  # Proton BattlEye Runtime
    1007020,  # Proton EasyAntiCheat Runtime
    1826330,  # Proton EasyAntiCheat Runtime
}
