"""The CachyOS package formats and the two checks every download must pass.

The repo database is not signed, so nothing in it is trusted on its own:
- the package's detached `.sig` must verify against the CachyOS key pinned in
  `data/cachyos_signing_key.asc`, by primary-key fingerprint, in a throwaway
  gpg home that holds that key and nothing else;
- the package's sha256 must equal both the db entry and the pinned lock.
Either failing stops the install before anything is extracted.

Pinned key: 882DCFE48E2051D48E2562ABF3B607488DB35A47 ("CachyOS
<admin@cachyos.org>"). The .sig names its own issuer, so it could not vouch
for the pin. Taken on 2026-11-22 from two other sources instead:
https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x882DCFE48E2051D48E2562ABF3B607488DB35A47
(the key file) and the long id F3B607488DB35A47 that CachyOS's own installer
imports, https://github.com/CachyOS/cachyos-repo-add-script/blob/5b27dc1eff276e104077cfaf75798b4c290eaef4/cachyos-repo.sh#L156
"""

from __future__ import annotations

import gzip
import hashlib
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

DATA = Path(__file__).parent / "data"
LOCK = DATA / "proton-native.lock"
KEY = DATA / "cachyos_signing_key.asc"
FINGERPRINT = "882DCFE48E2051D48E2562ABF3B607488DB35A47"
PREFIX = "usr/share/steam/compatibilitytools.d/proton-cachyos-native/"


class PkgError(Exception):
    pass


@dataclass(frozen=True)
class Lock:
    name: str
    repo: str  # URL of the <repo>.db
    version: str
    sha256: str


@dataclass(frozen=True)
class DbEntry:
    filename: str
    version: str
    sha256: str


@dataclass(frozen=True)
class MtreeEntry:
    kind: str  # "file", "link" or "dir"
    sha256: str = ""
    link: str = ""


def read_lock(path: Path = LOCK) -> Lock:
    fields = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    try:
        return Lock(fields["name"], fields["repo"], fields["version"], fields["sha256"])
    except KeyError as exc:
        raise PkgError(f"{path.name} has no {exc.args[0]}=") from exc


def package_url(lock: Lock, filename: str) -> str:
    """The package sits next to the db; the epoch colon must be escaped."""
    return f"{lock.repo.rsplit('/', 1)[0]}/{quote(filename)}"


def find_in_db(db: Path, name: str) -> DbEntry:
    """The db entry whose %NAME% is exactly `name` (not `<name>-v3`)."""
    with tarfile.open(db, "r:*") as tar:
        for member in tar:
            if not member.name.endswith("/desc"):
                continue
            fields = _desc(tar.extractfile(member).read().decode())
            if fields.get("NAME") == name:
                return DbEntry(fields["FILENAME"], fields["VERSION"], fields["SHA256SUM"])
    raise PkgError(f"the repo database lists no {name}")


def _desc(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for block in text.strip().split("\n\n"):
        head, _, value = block.partition("\n")
        fields[head.strip("%")] = value.strip()
    return fields


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gpg(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--no-tty", *args],
        capture_output=True, text=True, check=False, timeout=60,
    )


def key_fingerprints(key: Path, home: Path) -> list[str]:
    """Primary-key fingerprints in `key`, imported into the empty `home`."""
    _gpg(home, "--import", str(key))
    listing = _gpg(home, "--with-colons", "--fingerprint").stdout.splitlines()
    out, after_pub = [], False
    for line in listing:
        if line.startswith("pub"):
            after_pub = True
        elif line.startswith("fpr") and after_pub:
            out.append(line.split(":")[9])
            after_pub = False
    return out


def verify_signature(package: Path, sig: Path, key: Path, fingerprint: str, home: Path) -> None:
    """Fail unless `sig` is a good signature by the pinned primary key."""
    if fingerprint not in key_fingerprints(key, home):
        raise PkgError("the pinned key file does not hold the pinned fingerprint")
    result = _gpg(home, "--status-fd", "1", "--verify", str(sig), str(package))
    signers = [
        line.split()[-1]
        for line in result.stdout.splitlines()
        if line.startswith("[GNUPG:] VALIDSIG ")
    ]
    if result.returncode != 0 or signers != [fingerprint]:
        raise PkgError(f"package signature does not verify against {fingerprint}")


def _unescape(path: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def read_mtree(package: Path) -> dict[str, MtreeEntry]:
    """The package's own file list for the tool folder, relative to it."""
    with tarfile.open(package, "r:zst") as tar:
        for member in tar:
            if member.name == ".MTREE":
                text = gzip.decompress(tar.extractfile(member).read()).decode()
                break
        else:
            raise PkgError("package has no .MTREE")
    entries: dict[str, MtreeEntry] = {}
    defaults: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        path, *pairs = line.split(" ")
        values = dict(pair.partition("=")[::2] for pair in pairs)
        if path == "/set":
            defaults.update(values)
            continue
        path = _unescape(path.removeprefix("./"))
        if not path.startswith(PREFIX) or path == PREFIX:
            continue
        values = {**defaults, **values}
        entries[path[len(PREFIX):]] = MtreeEntry(
            values.get("type", "file"), values.get("sha256digest", ""), values.get("link", "")
        )
    return entries


def first_mismatch(folder: Path, entries: dict[str, MtreeEntry]) -> str | None:
    """The first path where `folder` differs from the package, or None.

    Files the package does not list count as a difference (a stray
    user_settings.py changes how Proton runs), except Python's own
    `__pycache__`, which running protonfixes creates.
    """
    for rel, entry in sorted(entries.items()):
        path = folder / rel
        if entry.kind == "link":
            if not path.is_symlink() or str(path.readlink()) != entry.link:
                return rel
        elif entry.kind == "file" and (
            path.is_symlink() or not path.is_file() or sha256_file(path) != entry.sha256
        ):
            return rel
    for path in sorted(folder.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        rel = str(path.relative_to(folder))
        if rel not in entries and "__pycache__" not in path.parts and rel != "VERSION":
            return rel
    return None


def extract(package: Path, dest: Path) -> None:
    """Unpack only the tool folder into `dest`; scripts are never run."""
    with tarfile.open(package, "r:zst") as tar:
        members = []
        for member in tar.getmembers():
            if member.name.startswith(PREFIX) and member.name != PREFIX:
                member.name = member.name[len(PREFIX):]
                members.append(member)
        tar.extractall(dest, members=members, filter="data")
