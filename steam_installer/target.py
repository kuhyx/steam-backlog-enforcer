"""Work out which Steam app the user meant from one free-form argument.

Four accepted forms, all resolving to the same app:

    284160
    https://steamcommunity.com/app/284160/guides/
    https://store.steampowered.com/app/284160/BeamNGdrive/
    BeamNG.drive
    BeamNG

Whatever the input, the appid is always confirmed against Steam's own app
cache (`appcache/appinfo.vdf`) before anything acts on it, so the name and
installdir used downstream come from Steam rather than from a search index that ranks
"Portal 2" above "Portal".
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sys

from steam_installer import appinfo, errors, resolve

# `app/<digits>` preceded by a delimiter: matches both store and community
# URLs, any trailing path or query, and `steam://` links. Not anchored to a
# scheme, so a bare "steamcommunity.com/app/284160" works too.
APP_URL_RE = re.compile(r"(?:^|[/?&])app/(\d+)(?:[/?#]|$)")


class TargetError(errors.InstallerError):
    """The input could not be resolved to exactly one Steam app."""


@dataclass(frozen=True)
class Resolved:
    """A target resolved to an app and its metadata."""

    metadata: appinfo.AppMetadata
    source: str  # "flag" | "appid" | "url" | "exact" | "picked"


def parse_literal(text: str) -> tuple[int, str] | None:
    """(appid, source) when the text literally names one, else None."""
    stripped = text.strip()
    if stripped.isdigit() and int(stripped) > 0:
        return int(stripped), "appid"
    match = APP_URL_RE.search(stripped)
    if match:
        return int(match.group(1)), "url"
    return None


def _confirm(appid: int, source: str) -> Resolved:
    try:
        return Resolved(appinfo.get_metadata(appid), source)
    except appinfo.AppInfoError as exc:
        msg = f"appid {appid} is not a known Steam app ({exc})"
        raise TargetError(msg) from exc


def _by_name(text: str, *, interactive: bool) -> Resolved:
    try:
        results = resolve.search(text)
    except resolve.SearchUnavailableError as exc:
        msg = f"Steam search is unavailable ({exc}). Pass the numeric AppID instead."
        raise TargetError(msg) from exc

    if not results:
        msg = f"No Steam app matches {text!r}."
        raise TargetError(msg)
    if len(results) == 1:
        return _confirm(results[0].appid, "only match")

    # Exact title first: Steam ranks "Portal 2" above "Portal", so without this
    # a fully-typed name silently installs the sequel.
    exact = resolve.exact_match(results, text)
    if exact is not None:
        return _confirm(exact.appid, "exact")

    if not interactive:
        # Fail closed. Guessing here is how the wrong 90 GB gets downloaded.
        sys.stderr.write(f"{text!r} is ambiguous. Candidates:\n")
        for result in results:
            sys.stderr.write(f"  {result.appid}  {result.name}\n")
        msg = (
            "Ambiguous name in a non-interactive run. Re-run with the exact "
            "title or the numeric AppID."
        )
        raise TargetError(msg)

    return _confirm(resolve.prompt_confirm(results).appid, "picked")


def resolve_target(
    text: str | None, appid: int | None, *, interactive: bool
) -> Resolved:
    """Resolve --appid, or a free-form target, to confirmed app metadata."""
    if appid is not None:
        return _confirm(appid, "flag")
    if text is None:
        msg = "No target given."
        raise TargetError(msg)

    literal = parse_literal(text)
    if literal is not None:
        candidate, source = literal
        try:
            return _confirm(candidate, source)
        except TargetError:
            # Digits are not unambiguous -- a game literally called "2048"
            # exists -- so an unknown appid falls through to a name search
            # rather than dead-ending. A URL cannot be a name, so it doesn't.
            if source != "appid":
                raise

    return _by_name(text, interactive=interactive)
