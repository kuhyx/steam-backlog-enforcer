"""Which commands stay usable under each lock.

A leaf module (no imports) so the CLI dispatcher in ``main._shared`` and the
root daemon's control socket consult ONE table: a lock the daemon enforced
differently from the CLI would be a way around it for anyone who can reach
the socket. ``main._shared`` cannot be imported by the daemon directly --
``main`` imports the enforce loop, which starts the control socket.
"""

from __future__ import annotations

# Commands that remain usable while the manual pick lock is active.
# Principle: only what is needed to release the lock (done/check) or
# that cannot change the game assignment (status, enforce, setup, serve).
_MANUAL_LOCK_EXEMPT_COMMANDS = frozenset(
    {
        "done",
        "check",
        "status",
        "enforce",
        "setup",
        "serve",
        "abandon-pick",
        # Allowed so a second game can be locked in alongside the first; the
        # cap inside cmd_pick_manual is what stops this being a way out.
        "pick-manual",
        # The daily gaming budget is orthogonal to which game is assigned, and
        # gaming-unblock is a recovery hatch for a stuck bind mount - locking
        # it behind a manual pick would leave Steam masked with no way back.
        "gaming-status",
        "gaming-unblock",
        "gaming-reset",
    }
)

# Commands that remain usable while a total gaming block is active. Far
# stricter than _MANUAL_LOCK_EXEMPT_COMMANDS: no done/pick/reset/
# add-exception - there is no in-app way to shorten a total block.
#
# gaming-unblock is included because a playtime bind mount makes the total
# block's own `pacman -R steam` fail EBUSY - it must stay reachable exactly
# when the two collide. gaming-reset is NOT included: it shortens enforcement.
# serve changes nothing itself (every job it starts is lock-checked on its own)
# and refusing it took the web UI down for the whole block, crash-looping its
# systemd unit, the first time anything restarted it.
_TOTAL_BLOCK_EXEMPT_COMMANDS = frozenset(
    {"status", "enforce", "gaming-status", "gaming-unblock", "serve"}
)
