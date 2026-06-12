#!/usr/bin/env bash
# Build the pure-logic host library and run the pytest suite.
# Isolates from any sourced ROS environment, whose pytest plugins (launch_testing)
# otherwise break collection on this machine.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip -q install pytest >/dev/null 2>&1 || true

make -C test/host >/dev/null

# The OTA failure-injection suite is a multi-minute stress test — run it separately
# via tools/test_ota.sh, not on every fast pure-logic run.
exec env PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    python -m pytest test/ --ignore=test/test_ota_flash.py "$@"
