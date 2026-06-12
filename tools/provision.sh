#!/usr/bin/env bash
# Provision both stages over USB (one-time / recovery): bootloader @ 0x10000000
# and application @ 0x10040000. After this, app updates go over Ethernet (OTA).
#
# Works whether the board is already in BOOTSEL (held the BOOTSEL button) or is
# running an app with a working USB reset interface. picotool may print a benign
# "rebooting" message after a forced reset.
set -uo pipefail
cd "$(dirname "$0")/.."

cmake --build build -j"$(nproc)" || exit 1

pt() { picotool "$@" 2>/dev/null || sudo picotool "$@"; }

if picotool info >/dev/null 2>&1 || sudo picotool info >/dev/null 2>&1; then
    echo "[provision] device already in BOOTSEL"
else
    echo "[provision] forcing BOOTSEL via app reset interface"
    pt reboot -f -u || true
    sleep 2
fi

echo "[provision] loading bootloader -> 0x10000000"
pt load build/bootloader.uf2 || { echo "bootloader load FAILED (put the board in BOOTSEL: hold BOOTSEL, tap RESET)"; exit 1; }
echo "[provision] loading application -> 0x10040000"
pt load build/keypad.uf2 || { echo "app load FAILED"; exit 1; }
echo "[provision] rebooting into flash (bootloader -> app)"
pt reboot || true
echo "[provision] done"
