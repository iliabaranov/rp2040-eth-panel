"""ctypes bindings for the pure firmware modules (built into libkeypadcore.so).

These are the SAME C sources compiled into the firmware (keypad, lighting,
protocol); here they run on the host so the logic is testable without hardware.
Since the keypad is not physically wired, keypad tests feed stubbed matrix
snapshots (lists of 0/1) rather than reading real GPIO.
"""
import ctypes
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "host", "libkeypadcore.so")

# Event types (keypad.h)
EV_DOWN, EV_UP, EV_REPEAT = 0, 1, 2
# Light modes (lighting.h)
OFF, SOLID, BLINK, PULSE = 0, 1, 2, 3
# Command types (protocol.h)
CMD_NONE, CMD_LIGHT, CMD_CONFIG, CMD_PING, CMD_UNKNOWN = 0, 1, 2, 3, 4


def load():
    lib = ctypes.CDLL(_LIB)

    lib.kp_new.restype = ctypes.c_void_p
    lib.kp_new.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.kp_free.argtypes = [ctypes.c_void_p]
    lib.kp_ghost.restype = ctypes.c_int
    lib.kp_ghost.argtypes = [ctypes.POINTER(ctypes.c_int)]
    lib.kp_update.restype = ctypes.c_int
    lib.kp_update.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.c_int,
    ]
    lib.kp_rows.restype = ctypes.c_int
    lib.kp_cols.restype = ctypes.c_int

    lib.li_new.restype = ctypes.c_void_p
    lib.li_free.argtypes = [ctypes.c_void_p]
    lib.li_set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint32]
    lib.li_duty.restype = ctypes.c_int
    lib.li_duty.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

    lib.pp_parse.restype = ctypes.c_int
    lib.pp_parse.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    cc, ci, cz, cu = ctypes.c_char_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_uint32
    lib.proto_fmt_key.restype = ci
    lib.proto_fmt_key.argtypes = [cc, cz, cc, cc, cu]
    lib.proto_fmt_hello.restype = ci
    lib.proto_fmt_hello.argtypes = [cc, cz, cc, ci, cc]
    lib.proto_fmt_ack.restype = ci
    lib.proto_fmt_ack.argtypes = [cc, cz, cc]
    lib.proto_fmt_err.restype = ci
    lib.proto_fmt_err.argtypes = [cc, cz, cc]
    return lib


class Keypad:
    """Wraps a keypad_t; feed stubbed snapshots, get events back."""

    def __init__(self, lib, debounce_ms, repeat_delay_ms, repeat_rate_ms):
        self.lib = lib
        self.rows = lib.kp_rows()
        self.cols = lib.kp_cols()
        self.n = self.rows * self.cols
        self.h = lib.kp_new(debounce_ms, repeat_delay_ms, repeat_rate_ms)

    def _flat(self, snapshot):
        """snapshot: rows x cols nested list, or flat list of len rows*cols."""
        if snapshot and isinstance(snapshot[0], (list, tuple)):
            flat = [int(bool(v)) for row in snapshot for v in row]
        else:
            flat = [int(bool(v)) for v in snapshot]
        assert len(flat) == self.n, f"expected {self.n} cells"
        return (ctypes.c_int * self.n)(*flat)

    def ghost(self, snapshot):
        return bool(self.lib.kp_ghost(self._flat(snapshot)))

    def update(self, snapshot, now_ms, max_events=32):
        arr = self._flat(snapshot)
        types = (ctypes.c_int * max_events)()
        rows = (ctypes.c_int * max_events)()
        cols = (ctypes.c_int * max_events)()
        n = self.lib.kp_update(self.h, arr, now_ms, types, rows, cols, max_events)
        return [(types[i], rows[i], cols[i]) for i in range(n)]

    def free(self):
        self.lib.kp_free(self.h)


class Lighting:
    def __init__(self, lib):
        self.lib = lib
        self.h = lib.li_new()

    def set(self, mode, brightness_pct, hz, now_ms):
        self.lib.li_set(self.h, mode, brightness_pct, hz, now_ms)

    def duty(self, now_ms):
        return self.lib.li_duty(self.h, now_ms)

    def free(self):
        self.lib.li_free(self.h)


def parse_cmd(lib, line):
    pat = ctypes.create_string_buffer(16)
    b = ctypes.c_int()
    hz = ctypes.c_int()
    deb = ctypes.c_int()
    rd = ctypes.c_int()
    rr = ctypes.c_int()
    t = lib.pp_parse(line.encode(), pat, 16,
                     ctypes.byref(b), ctypes.byref(hz),
                     ctypes.byref(deb), ctypes.byref(rd), ctypes.byref(rr))
    return {
        "type": t, "pattern": pat.value.decode(),
        "brightness": b.value, "hz": hz.value,
        "debounce_ms": deb.value, "repeat_delay_ms": rd.value,
        "repeat_rate_ms": rr.value,
    }


def _buf():
    return ctypes.create_string_buffer(128)

def fmt_key(lib, key, edge, ms):
    b = _buf()
    rc = lib.proto_fmt_key(b, 128, key.encode(), edge.encode(), ms)
    return rc, b.value.decode()

def fmt_hello(lib, fw, keys, ip):
    b = _buf()
    rc = lib.proto_fmt_hello(b, 128, fw.encode(), keys, ip.encode())
    return rc, b.value.decode()

def fmt_ack(lib, cmd):
    b = _buf()
    rc = lib.proto_fmt_ack(b, 128, cmd.encode())
    return rc, b.value.decode()

def fmt_err(lib, msg):
    b = _buf()
    rc = lib.proto_fmt_err(b, 128, msg.encode())
    return rc, b.value.decode()
