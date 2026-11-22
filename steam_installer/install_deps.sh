#!/bin/bash

# ============================================================================
# Install everything the Steam game installer shells out to.
#
#   libibus          the one runtime library of proton-cachyos-native's 63
#                    package dependencies a plain Arch desktop may lack (pacman)
#   depotdownloader  official self-contained release from SteamRE/DepotDownloader
#   kuhy-credit      the installer's one third-party import (user site, pinned in
#                    requirements.txt)
#   native Proton    proton-cachyos-native, pinned in
#                    steam_installer/data/proton-native.lock, signature- and
#                    sha256-checked, into Steam's compatibilitytools.d
#
# steamcmd is not needed any more: app info comes from Steam's own cache and
# the manifest is written by the tool itself.
#
# Idempotent: every step no-ops when its target is already in place, so
# steam_installer/run.sh can call it on every run. Installing libibus runs `sudo -n pacman`; when sudo
# would prompt, it stops and prints the one command to type.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly REPO_DIR="${SCRIPT_DIR%/*}"
readonly PYTHON="${SGI_PYTHON:-/usr/bin/python3}"
readonly STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/steam-game-installer"
readonly STAMP="${STATE_DIR}/.deps-ok"
readonly DD_REPO="SteamRE/DepotDownloader"
readonly DD_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/steam-game-installer/depotdownloader"
readonly BIN_DIR="${HOME}/.local/bin"

CHECK_ONLY=0
TEMP_DIR=""

cleanup() {
	if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
		rm -rf -- "$TEMP_DIR"
	fi
}
trap cleanup EXIT

usage() {
	echo "Usage: install.sh [OPTIONS]"
	echo "Options:"
	echo "  --check-only   Report missing dependencies without installing anything"
	echo "  -h, --help     Show this help"
	exit 0
}

die() {
	echo "error: $*" >&2
	exit 1
}

ensure_libibus() {
	if pacman -Q libibus >/dev/null 2>&1; then
		return 0
	fi
	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		echo "missing: libibus -- run: sudo pacman -S --needed libibus" >&2
		return 1
	fi
	sudo -n true 2>/dev/null ||
		die "libibus is missing and sudo needs a password. Run: sudo pacman -S --needed libibus"
	# No -y: syncing the db without upgrading is a partial upgrade on Arch.
	sudo -n pacman -S --needed --noconfirm libibus ||
		die "pacman could not install libibus (a stale package db 404s). Run: sudo pacman -Syu libibus"
}

# The installer's one third-party import. The daemon launches it with the
# system interpreter as the desktop user, so it must live in that user's site.
ensure_kuhy_credit() {
	if "$PYTHON" -c 'import kuhy_credit' >/dev/null 2>&1; then
		return 0
	fi
	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		echo "missing: kuhy-credit -- run steam_installer/install_deps.sh" >&2
		return 1
	fi
	local pin
	pin="$(grep -m1 '^kuhy-credit' "${REPO_DIR}/requirements.txt")" ||
		die "no kuhy-credit pin in ${REPO_DIR}/requirements.txt"
	"$PYTHON" -m pip install --user --break-system-packages "$pin" ||
		die "could not install kuhy-credit"
}

# Never runs the package's .INSTALL; see steam_installer/proton_native.py.
ensure_native_proton() {
	export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:$PYTHONPATH}"
	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		if ! "$PYTHON" -m steam_installer.proton_native --check; then
			echo "missing: proton-cachyos-native at the pinned version -- run steam_installer/install_deps.sh" >&2
			return 1
		fi
		return 0
	fi
	"$PYTHON" -m steam_installer.proton_native || die "native Proton install failed"
}

# Build from source only if the published binary can't be fetched. The upstream
# global.json pins the SDK to 9.0.x with rollForward=latestMinor, which will NOT
# roll forward to dotnet 10 -- so this needs dotnet-sdk-9.0 specifically.
build_depotdownloader() {
	local src="${HOME}/vendor/depotdownloader"
	[[ -d "$src" ]] || die "could not download DepotDownloader and no source tree at $src"
	command -v yay >/dev/null 2>&1 || die "need yay to install dotnet-sdk-9.0"
	pacman -Qq dotnet-sdk-9.0 >/dev/null 2>&1 ||
		yay -S --needed --noconfirm dotnet-sdk-9.0
	(cd "$src" && dotnet build -c Release)
	ln -sfn "${src}/DepotDownloader/bin/Release/net9.0/DepotDownloader" \
		"${BIN_DIR}/depotdownloader"
}

ensure_depotdownloader() {
	if command -v depotdownloader >/dev/null 2>&1; then
		return 0
	fi
	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		echo "missing: depotdownloader -- run steam_installer/install_deps.sh" >&2
		return 1
	fi

	mkdir -p "$BIN_DIR"
	echo "Fetching the latest DepotDownloader release..."
	local url=""
	url="$(curl -fsSL "https://api.github.com/repos/${DD_REPO}/releases/latest" |
		grep -oE '"browser_download_url": *"[^"]*linux-x64\.zip"' |
		cut -d'"' -f4 || true)"

	if [[ -n "$url" ]]; then
		TEMP_DIR="$(mktemp -d)"
		mkdir -p "$DD_HOME"
		# bsdtar ships with libarchive, a pacman dependency; unzip may not exist.
		curl -fsSL -o "${TEMP_DIR}/dd.zip" "$url" &&
			bsdtar -xf "${TEMP_DIR}/dd.zip" -C "$DD_HOME" &&
			chmod +x "${DD_HOME}/DepotDownloader" &&
			ln -sfn "${DD_HOME}/DepotDownloader" "${BIN_DIR}/depotdownloader"
	else
		echo "Release download unavailable; falling back to a source build." >&2
		build_depotdownloader
	fi

	command -v depotdownloader >/dev/null 2>&1 ||
		die "depotdownloader installed to ${BIN_DIR} but is not on PATH. Add ${BIN_DIR} to PATH."
}

main() {
	local missing=0
	ensure_libibus || missing=1
	ensure_depotdownloader || missing=1
	ensure_kuhy_credit || missing=1

	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		ensure_native_proton || missing=1
		[[ "$missing" -eq 0 ]] && echo "All dependencies present."
		exit "$missing"
	fi

	ensure_kuhy_credit
	ensure_native_proton
	echo "All dependencies present."
	mkdir -p "$STATE_DIR"
	: >"$STAMP"
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--check-only)
		CHECK_ONLY=1
		shift
		;;
	-h | --help)
		usage
		;;
	*)
		echo "Unknown option: $1" >&2
		exit 1
		;;
	esac
done

main
