"""Entry point: resolve -> confirm -> fast download -> make Steam recognize it."""

from __future__ import annotations

import argparse
import shutil
import sys
import time

from steam_installer import appinfo, depotdl, recognize, resolve
from steam_installer.library import find_steam_root, list_libraries, pick_install_target


def _require_tool(name: str, install_hint: str) -> None:
    if shutil.which(name) is None:
        print(f"error: `{name}` not found on PATH. {install_hint}", file=sys.stderr)
        sys.exit(1)


def _resolve_appid(args: argparse.Namespace) -> int:
    """Prefer an explicit --appid; fall back to search, which is best-effort
    (store.steampowered.com is known to reject scripted clients on some
    networks -- see resolve.py). Either way, the final confirmation uses the
    real name from steamcmd's own app info, not whatever the search returned.
    """
    if args.appid is not None:
        return args.appid

    try:
        results = resolve.search(args.name)
    except resolve.SearchUnavailable as exc:
        print(f"Store search unavailable ({exc}).", file=sys.stderr)
        print(
            "Find the numeric AppID yourself (e.g. from the store URL) and pass --appid.",
            file=sys.stderr,
        )
        sys.exit(1)

    chosen = resolve.prompt_confirm(results)
    return chosen.appid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download an owned Steam game fast, then make Steam recognize it."
    )
    parser.add_argument("name", nargs="?", default=None, help="Game name to search for")
    parser.add_argument(
        "--appid", type=int, default=None, help="Steam AppID (skips search)"
    )
    parser.add_argument("--username", required=True, help="Steam account username")
    parser.add_argument(
        "--language", default=None, help="Language depot to fetch (default: prompts)"
    )
    parser.add_argument(
        "--max-downloads", type=int, default=depotdl.DEFAULT_MAX_DOWNLOADS
    )
    args = parser.parse_args(argv)

    if args.appid is None and args.name is None:
        parser.error("provide a game name to search for, or --appid directly")

    _require_tool("depotdownloader", "See ~/depotdownloader.")
    _require_tool("steamcmd", "Run: yay -S steamcmd")

    appid = _resolve_appid(args)
    metadata = appinfo.get_metadata(appid)
    print(f"Confirmed: {metadata.name} (appid {metadata.appid})")
    answer = input("Proceed? [y/N]: ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return 1

    steam_root = find_steam_root()
    libraries = list_libraries(steam_root)
    target = pick_install_target(libraries, metadata.installdir)
    print(f"Install target: {target}")

    language = args.language
    if language is None:
        language = input("Language [english]: ").strip() or "english"

    print("Downloading via depotdownloader (fast path)...")
    depotdl.download(
        appid=metadata.appid,
        install_dir=target,
        username=args.username,
        language=language,
        max_downloads=args.max_downloads,
    )

    print("Reconciling with steamcmd (validate)...")
    library = next(lib for lib in libraries if lib.common == target.parent)
    result = recognize.run_steamcmd_validate(metadata.appid, target, args.username)

    if result.completed:
        print("steamcmd finished cleanly -- Steam should show Play.")
        return 0

    if result.crashed_on_install_script:
        print(
            "steamcmd hit the known install-script crash; finishing the manifest manually..."
        )
        manifest_path = recognize.finish_manifest_manually(
            library=library,
            appid=metadata.appid,
            install_dir=target,
            now_unix=int(time.time()),
        )
        print(f"Wrote {manifest_path} -- launch Steam and confirm Play works.")
        return 0

    print(
        "steamcmd failed for an unrecognized reason -- output above, not auto-resolved."
    )
    print(result.output[-4000:])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
