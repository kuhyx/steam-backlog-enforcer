"""Shared ProtonDB cache-file redirection for the protondb tests."""

from __future__ import annotations

from contextlib import contextmanager
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer.protondb"


def write_gold_cache(tmp_path: Path) -> Path:
    """Write a cache file rating app 440 gold and return its path."""
    cache_file = tmp_path / "protondb_cache.json"
    cache_file.write_text(json.dumps({"440": {"tier": "gold"}}), encoding="utf-8")
    return cache_file


@contextmanager
def cache_at(cache_file: Path) -> Iterator[None]:
    """Point the ProtonDB cache at ``cache_file`` for reads only."""
    with patch(f"{PKG}.PROTONDB_CACHE_FILE", cache_file):
        yield


@contextmanager
def writable_cache_at(cache_file: Path, config_dir: Path) -> Iterator[None]:
    """Point the cache file and its config dir at test paths so saves land there."""
    with cache_at(cache_file), patch(f"{PKG}.CONFIG_DIR", config_dir):
        yield
