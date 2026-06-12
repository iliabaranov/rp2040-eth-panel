"""Faithful simulator of the RP2040-ETH bootloader recovery receiver, fronted by a
CH9120-like byte-stream bridge with fault injection.

It exists to test the OTA *protocol* (host tools/ota_flash.py + the device framing
logic in bootloader/recovery.c) under the real-world transport quirks that caused
the field failures, without hardware:

  - the CH9120 is a single-client byte-stream bridge with NO framing, so a
    dropped/retried connection can leave stale bytes in flight (modelled by
    `pending_in`, which carries across reconnects);
  - UART RX can lose a byte under load (modelled by `drop_prob`);
  - the TCP link can blip mid-transfer (modelled by `reset_after`).

The device half mirrors bootloader/recovery.c exactly: the same 4-byte command
magics, the same sliding-window resync (`read_command`), per-chunk CRC + DACK/DNAK,
and whole-image CRC verify at END. If the firmware framing is sound, the host
flasher's retry/resync must drive this to a correct image every time the faults are
individually recoverable; the tests assert exactly that.
"""
import socket
import struct
import threading
import zlib

MAGICS = (b"RP2B", b"BEGN", b"DATA", b"END!", b"GO!!")
SLOT_SIZE = 0x3BE000      # APP_MAX_SIZE-ish; only what we report in BLOK
CHUNK = 1024


class _Eof(Exception):
    pass


class _Reader:
    """Byte source for one connection: drains the device's carried-over `pending_in`
    first, then the socket, applying random byte drops (UART-overrun model).

    Timeouts are short because on localhost a complete frame arrives near-instantly,
    so a byte that doesn't show up within the window is a genuinely lost byte — there
    is no point modelling the firmware's multi-second wait, which only made the test
    suite slow. `read_byte` returns None on timeout (no byte yet) and raises _Eof when
    the peer closes."""

    def __init__(self, sock, dev, faults):
        self.sock = sock
        self.dev = dev
        self.faults = faults

    def read_byte(self, timeout):
        if self.dev.pending_in:
            b = bytes(self.dev.pending_in[:1])
            del self.dev.pending_in[:1]
        else:
            self.sock.settimeout(timeout)
            try:
                b = self.sock.recv(1)
            except socket.timeout:
                return None
            except OSError:
                raise _Eof()
            if not b:
                raise _Eof()
        self.faults.bytes_seen += 1
        if self.faults.maybe_drop():
            return None  # lost byte: indistinguishable from "not arrived yet"
        return b

    def read_exact(self, n, timeout=0.3):
        """Collect exactly n bytes; return None if a byte fails to arrive within
        `timeout` (a lost byte mid-frame -> the device NAKs and the host re-sends)."""
        out = bytearray()
        while len(out) < n:
            b = self.read_byte(timeout)
            if b is None:
                return None
            out += b
        return bytes(out)


class Faults:
    """Tunable fault injector shared by a server for one test scenario."""

    def __init__(self, drop_prob=0.0, reset_after=None, stale_prefix=b"", rng=None):
        self.drop_prob = drop_prob
        self.reset_after = reset_after      # close the conn after N device-read bytes
        self.stale_prefix = stale_prefix    # bytes left in the bridge before each conn
        self.bytes_seen = 0
        self._rng = rng

    def maybe_drop(self):
        if self.drop_prob <= 0:
            return False
        return self._rng.random() < self.drop_prob


class Device:
    """Persistent device state: the flash slot and any bytes carried across a
    dropped connection. One instance survives all reconnects within a scenario."""

    def __init__(self):
        self.slot = bytearray()
        self.pending_in = bytearray()
        self.app_len = 0
        self.app_crc = 0
        self.committed = None     # bytes of the last image that reached DONE

    def _ensure(self, end):
        if len(self.slot) < end:
            self.slot += b"\xff" * (end - len(self.slot))


class _Reset(Exception):
    pass


def _check_reset(faults):
    if faults.reset_after is not None and faults.bytes_seen >= faults.reset_after:
        raise _Reset()


def _read_command(rd, faults):
    """Resync to a known command magic (mirrors recovery.c read_command). Waits
    across idle gaps until the peer closes; returns None on close."""
    window = b""
    while True:
        _check_reset(faults)
        try:
            b = rd.read_byte(0.3)
        except _Eof:
            return None
        if b is None:
            continue  # idle gap or lost byte; keep waiting (connection still open)
        window = (window + b)[-4:]
        if len(window) == 4 and window in MAGICS:
            return window


def _read_exact(rd, n, faults):
    _check_reset(faults)
    try:
        return rd.read_exact(n)
    except _Eof:
        return None


def _serve_connection(sock, dev, faults):
    rd = _Reader(sock, dev, faults)

    def send(b):
        try:
            sock.sendall(b)
        except OSError:
            raise _Reset()

    while True:
        tok = _read_command(rd, faults)
        if tok is None:
            return
        if tok == b"RP2B":
            _read_exact(rd, 4, faults)             # "OOT1"
            send(b"BLOK" + struct.pack("<II", SLOT_SIZE, CHUNK))
        elif tok == b"BEGN":
            hdr = _read_exact(rd, 8, faults)
            if hdr is None:
                continue
            dev.app_len, dev.app_crc = struct.unpack("<II", hdr)
            dev._ensure(dev.app_len)
            for i in range(dev.app_len):
                dev.slot[i] = 0xFF                  # erase
            send(b"OKER")
        elif tok == b"DATA":
            hdr = _read_exact(rd, 12, faults)
            if hdr is None:
                continue
            off, ln, ccrc = struct.unpack("<III", hdr)
            payload = _read_exact(rd, ln, faults)
            if payload is None or zlib.crc32(payload) & 0xFFFFFFFF != ccrc:
                send(b"DNAK" + struct.pack("<I", off))
                continue
            dev._ensure(off + ln)
            dev.slot[off:off + ln] = payload
            send(b"DACK" + struct.pack("<I", off))
        elif tok == b"END!":
            crc = zlib.crc32(bytes(dev.slot[:dev.app_len])) & 0xFFFFFFFF
            if crc == dev.app_crc:
                dev.committed = bytes(dev.slot[:dev.app_len])
                send(b"DONE")
            else:
                send(b"ECRC")
        elif tok == b"GO!!":
            send(b"BYE!")
            return


class SimServer:
    """A localhost TCP server running the device simulator. Use as a context
    manager; `.port` is the bound port, `.dev` the persistent device state."""

    def __init__(self, faults=None):
        self.faults = faults or Faults()
        self.dev = Device()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._stop = False
        self._t = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop = True
        try:
            self._srv.close()
        except OSError:
            pass

    def _loop(self):
        self._srv.settimeout(0.3)
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            # Stale bytes the bridge had buffered before this connection opened.
            if self.faults.stale_prefix:
                self.dev.pending_in += self.faults.stale_prefix
            conn.settimeout(5.0)
            try:
                _serve_connection(conn, self.dev, self.faults)
            except _Reset:
                # Link blip: the reset fires once, then the device keeps running.
                self.faults.reset_after = None
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
