"""Rebuild the web bundle when its sources are newer than ``web/dist``.

``_web_server`` reads ``web/dist`` per request, so a rebuild takes effect
without restarting anything - but nothing ever triggered one, which meant
``serve`` could quietly hand the browser a bundle older than the working tree.
This closes that gap: a stale bundle is rebuilt, and a build that fails stops
the launch rather than serving the old files under a new-looking process.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from steam_backlog_enforcer.game_install import _echo

WEB_DIR = (Path(__file__).resolve().parent.parent / "web").resolve()
_BUILT_MARKER = WEB_DIR / "dist" / "index.html"

# Everything whose change invalidates the built bundle. Anything under src,
# plus the build configuration itself - a vite/tsconfig edit changes the
# output even when not one line of src moved.
_SOURCE_DIR = WEB_DIR / "src"
_SOURCE_FILES = (
    WEB_DIR / "index.html",
    WEB_DIR / "package.json",
    WEB_DIR / "vite.config.ts",
    WEB_DIR / "tsconfig.json",
    WEB_DIR / "tsconfig.app.json",
    WEB_DIR / "tsconfig.node.json",
)

_BUILD_TIMEOUT_SECONDS = 600

_NPM_MISSING = (
    "npm was not found on PATH, so the stale web bundle cannot be rebuilt.\n"
    "npm is installed via nvm here, which only puts it on an interactive\n"
    "shell's PATH - a systemd unit or cron job will not see it. Either run\n"
    "serve from a normal shell, or build once by hand: cd web && npm run build"
)


def _mtime(path: Path) -> float:
    """Return the mtime of *path*, or 0.0 when it does not exist."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def frontend_is_stale() -> bool:
    """Check whether any build input is newer than the built bundle.

    A missing ``dist/index.html`` counts as stale so the first ``serve`` in a
    fresh clone builds instead of serving the "not built" placeholder.
    """
    built = _mtime(_BUILT_MARKER)
    if built == 0.0:
        return WEB_DIR.is_dir()
    sources = list(_SOURCE_FILES)
    if _SOURCE_DIR.is_dir():
        sources.extend(path for path in _SOURCE_DIR.rglob("*") if path.is_file())
    return any(_mtime(path) > built for path in sources)


def build_frontend() -> bool:
    """Run ``npm run build`` in ``web/``.

    Returns:
        True if the bundle was rebuilt, False if the build failed (the
        captured output is printed either way).
    """
    npm = shutil.which("npm")
    if npm is None:
        _echo(_NPM_MISSING)
        return False

    _echo("Frontend sources changed - rebuilding web/dist ...", flush=True)
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=WEB_DIR,
        capture_output=True,
        text=True,
        timeout=_BUILD_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        _echo("Frontend build FAILED - refusing to serve a stale bundle.\n")
        _echo(result.stdout.strip())
        _echo(result.stderr.strip())
        return False
    _echo("Frontend build complete.", flush=True)
    return True
