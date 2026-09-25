#!/usr/bin/env bash
# Camera Bridge dependency installer for Raspberry Pi OS / Debian.
# Run as the owner of the plugin folder: bash install.sh
# Optional: bash install.sh --dir /path/to/CameraBridge --force
# Prepares local dependencies for the included Camera Bridge plugin.
# No global pip packages, no global FFmpeg, no Domoticz restart.
set -Eeuo pipefail
umask 022

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
target_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
force=0
while (($#)); do
    case "$1" in
        --dir) (($# >= 2)) || die '--dir requires a path'; target_dir="$2"; shift 2 ;;
        --force) force=1; shift ;;
        -h|--help)
            printf '%s\n' 'Usage: bash install.sh [--dir PATH] [--force]' \
                'Default destination: the directory containing this script.' \
                'Run as the owner of the Domoticz plugin directory, without sudo.' \
                'sudo is used only if missing system utilities need installation.'
            exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done
[[ "$(uname -s)" == Linux ]] || die 'Linux is required.'
command -v dpkg >/dev/null || die 'Raspberry Pi OS or Debian is required.'
# Detect userland, not kernel: a 64-bit kernel may run a 32-bit OS.
case "$(dpkg --print-architecture)" in
    arm64) build_arch=arm64 ;;
    armhf)
        case "$(uname -m)" in armv6*) die 'This installer requires ARMv7 or newer for a 32-bit OS.' ;; esac
        build_arch=armhf ;;
    *) die 'Supported OS architectures: arm64 and armhf (ARMv7 or newer).' ;;
esac
if ((EUID == 0)); then
    die 'Run without sudo, as the owner of the plugin folder, to avoid root-owned plugin files.'
fi
mkdir -p -- "$target_dir/bin"
target_dir="$(cd -- "$target_dir" && pwd)"
[[ -w "$target_dir/bin" ]] || die "Directory is not writable: $target_dir/bin"

missing=()
command -v python3 >/dev/null || missing+=(python3)
command -v curl >/dev/null || missing+=(curl)
command -v xz >/dev/null || missing+=(xz-utils)
command -v tar >/dev/null || missing+=(tar)
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || missing+=(ca-certificates)
if ((${#missing[@]})); then
    command -v sudo >/dev/null || die "Ask the administrator to install: ${missing[*]}"
    printf 'Installing missing system utilities: %s\n' "${missing[*]}"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends "${missing[@]}"
fi
python3 -c 'import http.server, threading, subprocess, json, socket, ssl' \
    || die 'Python standard library check failed.'

work_dir="$(mktemp -d "$target_dir/.install-XXXXXXXX")"
cleanup() { rm -rf -- "$work_dir"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

check_ffmpeg() {
    local executable="$1"
    "$executable" -version > "$work_dir/version.txt" 2>&1 || return 1
    "$executable" -hide_banner -loglevel error -nostdin -y \
        -f lavfi -i 'color=c=black:s=64x64:r=1' -frames:v 1 \
        -c:v mjpeg -threads 1 -f image2 "$work_dir/test.jpg" || return 1
    python3 - "$work_dir/test.jpg" <<'PY'
import pathlib, sys
data = pathlib.Path(sys.argv[1]).read_bytes()
if not (data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9')):
    raise SystemExit('JPEG validation failed')
PY
}

if [[ -x "$target_dir/bin/ffmpeg" ]] && ((force == 0)); then
    check_ffmpeg "$target_dir/bin/ffmpeg" \
        || die 'Existing local FFmpeg failed validation. Run again with --force to replace it.'
    printf 'Existing local FFmpeg works; keeping it.\n'
else
    # Third-party static binaries, GPLv3. Source/build information:
    # https://johnvansickle.com/ffmpeg/
    base_url="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${build_arch}-static.tar.xz"
    printf 'Downloading local FFmpeg (%s)...\n' "$build_arch"
    curl --fail --location --proto '=https' --proto-redir '=https' \
        --retry 3 --connect-timeout 20 --max-time 900 \
        "$base_url" -o "$work_dir/ffmpeg.tar.xz"
    curl --fail --location --proto '=https' --proto-redir '=https' \
        --retry 3 --connect-timeout 20 --max-time 120 \
        "${base_url}.md5" -o "$work_dir/checksum.txt"
    # Upstream MD5 detects transfer corruption; it is not a digital signature.
    # Extract only the executable and licensing/readme files, without trusting paths.
    python3 - "$work_dir" <<'PY'
import hashlib, pathlib, re, shutil, sys, tarfile
root = pathlib.Path(sys.argv[1])
match = re.search(r'(?i)\b[0-9a-f]{32}\b', (root / 'checksum.txt').read_text())
digest = hashlib.md5()
with (root / 'ffmpeg.tar.xz').open('rb') as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
if not match or digest.hexdigest() != match.group().lower():
    raise SystemExit('Download checksum mismatch; no binary installed.')
with tarfile.open(root / 'ffmpeg.tar.xz', 'r:xz') as archive:
    binaries = [m for m in archive.getmembers()
                if m.isfile() and pathlib.PurePosixPath(m.name).name == 'ffmpeg']
    if len(binaries) != 1:
        raise SystemExit('Unexpected archive layout')
    with archive.extractfile(binaries[0]) as src, (root / 'ffmpeg').open('wb') as dst:
        shutil.copyfileobj(src, dst)
    for name in ('GPLv3.txt', 'readme.txt'):
        matches = [m for m in archive.getmembers()
                   if m.isfile() and pathlib.PurePosixPath(m.name).name == name]
        if len(matches) == 1:
            with archive.extractfile(matches[0]) as src, (root / name).open('wb') as dst:
                shutil.copyfileobj(src, dst)
PY
    chmod 755 "$work_dir/ffmpeg"
    check_ffmpeg "$work_dir/ffmpeg" || die 'Downloaded FFmpeg cannot generate a JPEG on this system.'
    # Same filesystem: atomic replacement, only after successful validation.
    mv -f -- "$work_dir/ffmpeg" "$target_dir/bin/ffmpeg"
    mkdir -p -- "$target_dir/bin/ffmpeg-docs"
    for doc in GPLv3.txt readme.txt; do
        if [[ -f "$work_dir/$doc" ]]; then
            cp -- "$work_dir/$doc" "$target_dir/bin/ffmpeg-docs/$doc"
        fi
    done
fi
printf '\nDependencies ready. FFmpeg path: %s/bin/ffmpeg\n' "$target_dir"
head -n 1 "$work_dir/version.txt"
printf '%s\n' 'JPEG generation test: OK.' \
    'No virtual environment is needed for the planned standard-library-only plugin.' \
    'Domoticz has not been restarted. Camera RTSP access has not been tested.'
if [[ ! -f "$target_dir/plugin.py" ]]; then
    printf '%s\n' 'NOTE: plugin.py is missing. Copy the complete CameraBridge directory from the ZIP.'
fi

if [[ -f "$target_dir/plugin.py" && -f "$target_dir/camera_bridge.py" ]]; then
    python3 - "$target_dir" <<'PYCODE'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1])
for name in ('plugin.py', 'camera_bridge.py'):
    ast.parse((root / name).read_text(), filename=name)
print('Plugin source checks: OK. Restart Domoticz and add Camera Bridge hardware.')
PYCODE
fi
