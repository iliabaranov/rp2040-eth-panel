"""Extensive failure-injection tests for the OTA path.

Runs the real host flasher (tools/ota_flash.py) against a faithful device+CH9120
simulator (ota_sim.py) hundreds of times across clean and fault-injected scenarios,
asserting the device ends up with a byte-exact image every time the faults are
individually recoverable. This is the regression guard for the field failures where
the OTA timed out at a *random* phase (a framing-desync transport bug).
"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ota_flash  # noqa: E402

from ota_sim import SimServer, Faults  # noqa: E402


@pytest.fixture
def image(tmp_path):
    # A few KB of pseudo-random, deterministic content -> several DATA chunks.
    data = random.Random(1234).randbytes(6000)
    p = tmp_path / "app.bin"
    p.write_bytes(data)
    return str(p), data


def _flash(server, image_path, retries=4):
    ota_flash.PORT = server.port
    ota_flash.flash("127.0.0.1", image_path, in_recovery=True, retries=retries)


def test_clean_repeated(image):
    """No faults: 40 back-to-back pushes must each land a byte-exact image."""
    path, data = image
    for _ in range(40):
        with SimServer() as srv:
            _flash(srv, path)
            assert srv.dev.committed == data


def test_stale_prefix(image):
    """Stray bytes (incl. a duplicate SYNC) left in the bridge before connecting
    must be skipped by both ends' resync, not desync the session."""
    path, data = image
    prefixes = [b"\x00\x01\x02\x03", b"OOT1garbage", b"RP2BOOT1", b"DACK\x00\x00\x00\x00",
                bytes(random.Random(7).randbytes(37))]
    for pre in prefixes:
        for _ in range(8):
            with SimServer(Faults(stale_prefix=pre)) as srv:
                _flash(srv, path)
                assert srv.dev.committed == data


def test_link_reset_midflight(image):
    """A TCP blip mid-transfer must be recovered by the whole-flash retry; the
    half-written slot is harmless."""
    path, data = image
    for reset_after in (30, 1100, 2500, 5000):
        for _ in range(6):
            with SimServer(Faults(reset_after=reset_after)) as srv:
                _flash(srv, path)
                assert srv.dev.committed == data


@pytest.mark.parametrize("drop_prob", [0.0003, 0.0008, 0.0015])
def test_byte_drops(image, drop_prob):
    """Lost bytes corrupt frames; per-chunk CRC+DNAK retries and command resync
    must still converge on a byte-exact image. (A sustained per-byte loss above
    ~1/chunk is not physical for this lock-step link — the device isn't busy during
    reception — so the rates here model occasional single-byte losses.)"""
    path, data = image
    for seed in range(10):
        faults = Faults(drop_prob=drop_prob, rng=random.Random(seed))
        with SimServer(faults) as srv:
            _flash(srv, path, retries=8)
            assert srv.dev.committed == data


def test_combined_stress(image):
    """Stale bytes + drops + a reset together — the worst realistic case."""
    path, data = image
    for seed in range(12):
        rng = random.Random(1000 + seed)
        faults = Faults(drop_prob=0.0008, reset_after=1500 + seed * 200,
                        stale_prefix=b"RP2BOOT1\x00\x00", rng=rng)
        with SimServer(faults) as srv:
            _flash(srv, path, retries=10)
            assert srv.dev.committed == data
