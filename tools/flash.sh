#!/usr/bin/env bash
# Build and flash the firmware to a running RP2040-ETH (force-reboot to BOOTSEL).
# Usage: tools/flash.sh [--no-build]
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" != "--no-build" ]]; then
    cmake --build build -j"$(nproc)"
fi

UF2=build/panel.uf2
[[ -f "$UF2" ]] || { echo "missing $UF2 — configure with: cmake -S firmware -B build" >&2; exit 1; }

# Try without sudo first (works if the 99-picotool.rules udev rule is active for
# the current connection); fall back to sudo.
if picotool load "$UF2" -fx 2>/dev/null; then
    echo "flashed (non-root)"
else
    sudo picotool load "$UF2" -fx
fi
