#!/usr/bin/env python3
"""Over-Ethernet firmware flasher for the RP2040-ETH bootloader.

Pushes an application image (the raw .bin, which loads at the slot base) to the
device's bootloader recovery server over TCP. If the device is running the app, it
is first asked to reboot into recovery ({"cmd":"ota"}), then reconnected to.

Protocol (see docs/OTA.md): SYNC -> BEGIN(len,crc) -> DATA(off,len,crc,payload)*
-> END -> GO. Lock-step: each DATA waits for DACK before the next.

Robustness: the CH9120 is a single-client byte-stream bridge with no framing, so a
dropped/retried connection can leave stale bytes in flight. Both ends resync to
known token boundaries; the host also drains stale bytes between phases and retries
the whole flash on a fresh connection if any phase fails (a half-written slot is
harmless — the bootloader stays in recovery and CRC gates the boot).

Usage:
    tools/ota_flash.py --host 10.74.29.13 build/keypad.bin
    tools/ota_flash.py --host 10.74.29.13 --in-recovery build/keypad.bin
"""
import argparse
import socket
import struct
import sys
import time
import zlib

PORT = 5005
CHUNK = 1024            # must match OTA_CHUNK_SIZE
SYNC = b"RP2BOOT1"

# Every device->host response begins with one of these 4-byte tokens.
KNOWN_RESP = (b"BLOK", b"OKER", b"DACK", b"DNAK", b"ECRC", b"DONE", b"BYE!", b"ERSZ")


def recv_exact(s, n, timeout=8.0):
    s.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        d = s.recv(n - len(buf))
        if not d:
            raise ConnectionError("peer closed")
        buf += d
    return buf


def read_token(s, expected, timeout=8.0):
    """Resync to a 4-byte response token, skipping stray/stale bytes.

    `expected` is a tuple of acceptable tokens. Returns the matched token. Raises
    socket.timeout if no acceptable token arrives within `timeout`. Skipping is
    bounded to known tokens, so a leftover response from a prior phase (e.g. a
    duplicate BLOK) is discarded rather than mistaken for the one we want."""
    deadline = time.time() + timeout
    window = b""
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise socket.timeout(f"timed out waiting for {expected}")
        s.settimeout(remaining)
        b = s.recv(1)
        if not b:
            raise ConnectionError("peer closed")
        window = (window + b)[-4:]
        if len(window) == 4 and window in expected:
            return window


def drain(s, settle=0.4):
    """Discard buffered bytes left over from a prior/retried connection."""
    s.settimeout(settle)
    try:
        while True:
            if not s.recv(4096):
                break
    except (socket.timeout, OSError):
        pass


def connect(host, timeout=5.0):
    return socket.create_connection((host, PORT), timeout=timeout)


def try_sync(s):
    """Return (slot_size, max_chunk) if the bootloader answers, else None."""
    drain(s, settle=0.2)
    s.sendall(SYNC)
    try:
        read_token(s, (b"BLOK",), timeout=3.0)
        info = recv_exact(s, 8, timeout=3.0)
    except (ConnectionError, socket.timeout, OSError):
        return None
    return struct.unpack("<II", info)


def send_trigger(s):
    """Ask a running app to reboot into recovery, and confirm it heard us.

    Returns True if the app acked (it will now reboot). Sent on the SAME socket as
    the SYNC probe — the CH9120 is a single-client server and a second socket to a
    running app wedges it. The ack matters: just after a reboot the app spends ~10 s
    reconfiguring the CH9120, during which it isn't reading the socket, so a blind
    one-shot trigger is easily lost — we must verify it landed and otherwise re-send."""
    try:
        drain(s, settle=0.2)
        s.sendall(b'{"cmd":"ota"}\n')
        s.settimeout(3.0)
        got = b""
        while b'"ack"' not in got:
            d = s.recv(256)
            if not d:
                break
            got += d
    except (OSError, socket.timeout):
        pass
    return b'"ack"' in got


def ensure_recovery(host, in_recovery):
    """Drive the device into bootloader recovery and return a synced socket +
    (slot_size, max_chunk).

    Source of truth is SYNC: if the bootloader answers BLOK we are in recovery. If
    instead the app answers, we re-send the update trigger until either the app acks
    (then it reboots and recovery comes up) or recovery starts answering directly.
    This loop is robust to a lost trigger, to the post-reboot CH9120 re-init window,
    and to being called when the device is already in recovery (the JSON trigger is
    harmless junk there — the receiver resyncs past it)."""
    deadline = time.time() + 150
    announced = False
    while time.time() < deadline:
        try:
            s = connect(host, timeout=3.0)
        except OSError:
            time.sleep(1.5)
            continue
        info = try_sync(s)
        if info:
            return s, info                      # in recovery — done
        # Not recovery: it's the running app (or it's mid-reboot / not ready yet).
        if not in_recovery:
            if not announced:
                print("[ota] device running app; requesting update mode...")
                announced = True
            acked = send_trigger(s)
            s.close()
            # If acked, it's rebooting (recovery up in ~15-25s); otherwise the app
            # wasn't ready — back off and re-probe/re-trigger.
            time.sleep(3.0 if acked else 2.0)
        else:
            s.close()
            time.sleep(2.0)                     # asserted in-recovery; just wait for SYNC
    raise TimeoutError("device never entered bootloader recovery")


def push_image(s, info, data, crc, chunk_retries=25):
    """Run one full SYNC'd push over socket `s`. Raises on any failure.

    A NAK'd chunk is a cheap, local recovery (re-send 1 KB), so it is retried
    generously. A connection-level fault (peer close / token timeout) is NOT caught
    here — it propagates to flash()'s whole-flash retry, which restarts from SYNC on
    a fresh connection. This split keeps the common case (an occasional corrupt
    chunk) from triggering an expensive, slow-to-converge full restart."""
    slot_size, max_chunk = info
    print(f"[ota] bootloader ready: slot={slot_size} bytes, max_chunk={max_chunk}")
    if len(data) > slot_size:
        raise RuntimeError("image larger than slot")

    # BEGIN — erase can take a moment; drain any stale bytes first.
    drain(s, settle=0.2)
    s.sendall(b"BEGN" + struct.pack("<II", len(data), crc))
    read_token(s, (b"OKER",), timeout=30.0)

    # DATA — lock-step, each chunk waits for its DACK.
    chunk = min(CHUNK, max_chunk)
    sent = 0
    for off in range(0, len(data), chunk):
        payload = data[off:off + chunk]
        pkt = b"DATA" + struct.pack("<III", off, len(payload),
                                    zlib.crc32(payload) & 0xFFFFFFFF) + payload
        for attempt in range(chunk_retries):
            s.sendall(pkt)
            tok = read_token(s, (b"DACK", b"DNAK"), timeout=8.0)
            ack_off = struct.unpack("<I", recv_exact(s, 4, timeout=8.0))[0]
            if tok == b"DACK" and ack_off == off:
                break
            if attempt + 1 == chunk_retries or (attempt + 1) % 5 == 0:
                print(f"\n[ota] chunk @{off} {tok!r}, retry {attempt + 1}/{chunk_retries}")
        else:
            raise RuntimeError(f"chunk @{off} failed after {chunk_retries} retries")
        sent += len(payload)
        pct = 100 * sent // len(data)
        sys.stdout.write(f"\r[ota] {sent}/{len(data)} ({pct}%)")
        sys.stdout.flush()
    print()

    # END — whole-image CRC verify on the device.
    s.sendall(b"END!")
    tok = read_token(s, (b"DONE", b"ECRC"), timeout=15.0)
    if tok != b"DONE":
        raise RuntimeError(f"image verification failed on device: {tok!r}")
    print("[ota] image verified on device")

    # GO — reboot into the new app (BYE! is best-effort; the link drops on reboot).
    s.sendall(b"GO!!")
    try:
        read_token(s, (b"BYE!",), timeout=3.0)
    except (ConnectionError, socket.timeout, OSError):
        pass
    print("[ota] rebooting into new app — done")


def flash(host, image, in_recovery, retries=3):
    data = open(image, "rb").read()
    crc = zlib.crc32(data) & 0xFFFFFFFF
    print(f"[ota] image {image}: {len(data)} bytes, crc32=0x{crc:08x}")

    last_err = None
    for attempt in range(1, retries + 1):
        s = None
        try:
            # ensure_recovery re-probes SYNC and re-triggers as needed every attempt,
            # so a failed push (whether it reached recovery or never triggered) is
            # handled the same way: drive the device back into recovery, then push.
            s, info = ensure_recovery(host, in_recovery)
            push_image(s, info, data, crc)
            return
        except (RuntimeError, ConnectionError, socket.timeout, OSError, TimeoutError) as e:
            last_err = e
            print(f"\n[ota] attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                print("[ota] retrying on a fresh connection "
                      "(half-written slot is safe; bootloader stays in recovery)...")
                time.sleep(2)
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
    raise RuntimeError(f"OTA failed after {retries} attempts: {last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="application .bin (loads at the slot base)")
    ap.add_argument("--host", required=True, help="device IP")
    ap.add_argument("--in-recovery", action="store_true",
                    help="device is already in bootloader recovery (skip the app trigger)")
    ap.add_argument("--retries", type=int, default=3, help="whole-flash retry attempts")
    args = ap.parse_args()
    try:
        flash(args.host, args.image, args.in_recovery, args.retries)
    except Exception as e:
        print(f"\n[ota] FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
