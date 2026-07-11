#!/usr/bin/env python3
"""Fail if the package imports a third-party dist not declared in requirements.

CI installs *only* ``requirements.txt`` (never the pyproject dependency list),
so an import added to the source but not mirrored into ``requirements.txt``
passes locally — where the dev environment already has it — and only blows up
in CI with ``ModuleNotFoundError``. This static check closes that gap at commit
time: it walks the package's own modules, collects every top-level third-party
import, and verifies each one's distribution is listed in ``requirements.txt``.

It is intentionally conservative — it only flags *direct* imports (things the
source explicitly ``import``s), never transitive dependencies — because you
should declare what you import rather than lean on someone else's dependency
tree. The pre-push clean-venv run is the definitive backstop for anything this
heuristic misses.

Usage (defaults auto-detect the single top-level package and repo-root
requirements.txt)::

    python3 scripts/check_requirements_sync.py
    python3 scripts/check_requirements_sync.py --package screen_locker \
        --requirements requirements.txt
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import sys

# Import-name -> distribution-name overrides for the rare cases where PEP 503
# normalisation (lowercase, runs of -/_/. collapsed to '-') is not enough.
# Most packages import under their normalised dist name (crdt_sync ->
# crdt-sync); add an entry here only when they genuinely diverge (the classic
# example being ``import dateutil`` shipped by ``python-dateutil``).
_IMPORT_TO_DIST: dict[str, str] = {
    "dateutil": "python-dateutil",
    "yaml": "pyyaml",
}


def _normalise(name: str) -> str:
    """Return the PEP 503 canonical form of a distribution/import name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(requirements: Path) -> set[str]:
    """Parse distribution names from a requirements.txt file.

    Handles the forms this monorepo uses: ``name``, ``name>=x``, ``name==x``,
    ``name[extra]``, and ``name @ git+https://...``. Comments, blank lines and
    ``-r``/``-c`` include directives are ignored.
    """
    names: set[str] = set()
    for raw_line in requirements.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        # The distribution name is the leading token before any version
        # specifier, extras bracket, environment marker or ``@`` URL.
        token = re.split(r"[\s@<>=!~;\[]", line, maxsplit=1)[0]
        if token:
            names.add(_normalise(token))
    return names


def _iter_package_modules(package_dir: Path) -> list[Path]:
    """Return the package's own .py files, excluding any tests directory."""
    return [
        path
        for path in sorted(package_dir.rglob("*.py"))
        if "tests" not in path.relative_to(package_dir).parts
    ]


def _top_level_imports(module: Path) -> set[str]:
    """Collect top-level module names imported by a single source file.

    ``import a.b`` and ``from a.b import c`` both contribute ``a``. Relative
    imports (``from . import x``) are skipped — they are first-party by
    definition.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".", 1)[0])
    return imported


def _third_party_imports(package_dir: Path, package_name: str) -> set[str]:
    """Return third-party top-level imports across the whole package.

    Standard-library modules (via ``sys.stdlib_module_names``) and the package's
    own name are filtered out, leaving only external dependencies.
    """
    stdlib = sys.stdlib_module_names
    external: set[str] = set()
    for module in _iter_package_modules(package_dir):
        for name in _top_level_imports(module):
            if name != package_name and name not in stdlib:
                external.add(name)
    return external


def _distribution_for(import_name: str) -> str:
    """Map a top-level import name to its (normalised) distribution name."""
    override = _IMPORT_TO_DIST.get(import_name)
    return _normalise(override if override is not None else import_name)


def _detect_package(root: Path) -> str:
    """Find the single top-level importable package directory under ``root``.

    Raises SystemExit with a helpful message if zero or several candidates
    exist, in which case ``--package`` must be given explicitly.
    """
    candidates = [
        child.name
        for child in sorted(root.iterdir())
        if child.is_dir()
        and (child / "__init__.py").is_file()
        and child.name != "tests"
    ]
    if len(candidates) != 1:
        sys.exit(
            "Could not auto-detect a single package "
            f"(found {candidates or 'none'}); pass --package explicitly.",
        )
    return candidates[0]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        help="Top-level package name (auto-detected when omitted).",
    )
    parser.add_argument(
        "--requirements",
        default="requirements.txt",
        help="Path to requirements.txt (default: %(default)s).",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to resolve paths against (default: %(default)s).",
    )
    return parser.parse_args(argv)


def check(package: str, package_dir: Path, requirements: Path) -> list[str]:
    """Return a sorted list of imported dists missing from requirements.txt."""
    declared = _requirement_names(requirements)
    missing = {
        name
        for name in _third_party_imports(package_dir, package)
        if _distribution_for(name) not in declared
    }
    return sorted(missing)


def main(argv: list[str] | None = None) -> int:
    """Entry point: exit non-zero (with a report) when deps are missing."""
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    package = args.package or _detect_package(root)
    package_dir = root / package
    requirements = root / args.requirements

    if not package_dir.is_dir():
        sys.exit(f"Package directory not found: {package_dir}")
    if not requirements.is_file():
        sys.exit(f"Requirements file not found: {requirements}")

    missing = check(package, package_dir, requirements)
    if missing:
        joined = "\n  - ".join(missing)
        sys.stderr.write(
            f"{package}: these third-party imports are not declared in "
            f"{requirements.name} (CI installs only that file, so they will "
            f"fail with ModuleNotFoundError):\n  - {joined}\n",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
