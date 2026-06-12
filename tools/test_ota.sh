#!/usr/bin/env bash
# OTA failure-injection stress suite: runs the real host flasher (tools/ota_flash.py)
# against the device+CH9120 simulator (test/ota_sim.py) across hundreds of pushes with
# injected faults (stale bytes, mid-transfer resets, byte loss). Multi-minute by design
# — this is the regression guard for the OTA framing-desync bug, kept out of the fast
# tools/test.sh run. No hardware required.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip -q install pytest >/dev/null 2>&1 || true

exec env PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    python -m pytest test/test_ota_flash.py -v "$@"
