#!/bin/bash

# ============================================================================
# Install everything this tool shells out to, then set up the dev environment.
#
#   libibus          the one runtime library of proton-cachyos-native's 63
#                    package dependencies a plain Arch desktop may lack (pacman)
#   depotdownloader  official self-contained release from SteamRE/DepotDownloader
#   .venv            local virtualenv with the package installed editable
#   native Proton    proton-cachyos-native, pinned in
#                    steam_installer/data/proton-native.lock, signature- and
#                    sha256-checked, into Steam's compatibilitytools.d
#
# steamcmd is not needed any more: app info comes from Steam's own cache and
# the manifest is written by the tool itself.
#
# Idempotent: every step no-ops when its target is already in place, so run.sh
# can call it on every run. Installing libibus runs `sudo -n pacman`; when sudo
# would prompt, it stops and prints the one command to type.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly VENV="${SCRIPT_DIR}/.venv"
readonly STAMP="${VENV}/.deps-ok"
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
	sudo -n pacman -S --needed --noconfirm libibus ||
		die "libibus is missing and sudo needs a password. Run: sudo pacman -S --needed libibus"
}

# Never runs the package's .INSTALL; see steam_installer/proton_native.py.
ensure_native_proton() {
	local python="${VENV}/bin/python"
	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		if [[ -x "$python" ]] && ! "$python" -m steam_installer.proton_native --check; then
			echo "missing: proton-cachyos-native at the pinned version -- run ./install.sh" >&2
			return 1
		fi
		return 0
	fi
	"$python" -m steam_installer.proton_native || die "native Proton install failed"
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
		echo "missing: depotdownloader -- run ./install.sh" >&2
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

# The suite requires 100% coverage (pyproject: fail_under = 100), and one test
# runs `python -m steam_installer.cli` in a subprocess. Coverage in a child is
# only recorded if it calls coverage.process_startup() at interpreter start,
# which is what this .pth does. Without it a clean clone reports 99% and fails.
setup_dev_env() {
	if [[ ! -x "${VENV}/bin/python" ]]; then
		echo "Creating ${VENV}..."
		python3 -m venv "$VENV"
	fi

	local python="${VENV}/bin/python"
	"$python" -m pip install -q --upgrade pip
	# Named outright rather than via an extra: pyproject declares none, and pip
	# only *warns* about a missing extra before exiting 0 -- so the old
	# `[dev] || fallback` form silently installed no test tools at all on a
	# fresh venv, and the .pth below then failed to import coverage.
	"$python" -m pip install -q -e "$SCRIPT_DIR" pytest pytest-cov coverage

	local site_packages
	site_packages="$("$python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
	cat >"${site_packages}/steam_installer_coverage.pth" <<-'PTH'
		import os, coverage; os.environ.get("COVERAGE_PROCESS_START") and coverage.process_startup()
	PTH
	"$python" -c 'import pytest, coverage' ||
		die "dev environment incomplete: pytest/coverage did not install"
	echo "Dev environment ready (subprocess coverage enabled)."
}

main() {
	local missing=0
	ensure_libibus || missing=1
	ensure_depotdownloader || missing=1

	if [[ "$CHECK_ONLY" -eq 1 ]]; then
		ensure_native_proton || missing=1
		[[ "$missing" -eq 0 ]] && echo "All dependencies present."
		exit "$missing"
	fi

	setup_dev_env
	ensure_native_proton
	echo "All dependencies present."
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
