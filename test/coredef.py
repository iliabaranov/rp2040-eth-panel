"""ctypes bindings for the pure firmware modules (built into libpanelcore.so).

These are the SAME C sources compiled into the firmware (buttons, rings,
protocol); here they run on the host so the logic is testable without hardware.
Tests feed raw button levels / ring commands plus a synthetic millisecond
clock — no struct layouts are mirrored in Python (the shim flattens them).
"""
import ctypes
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "host", "libpanelcore.so")

# Command types — order MUST mirror the proto_cmd_type enum in protocol.h.
CMD_NONE, CMD_RING, CMD_LAMP, CMD_CONFIG, CMD_PING, CMD_OTA, CMD_UNKNOWN = range(7)
# Pixel orders (rings.h ring_order_t)
ORDER_GRB, ORDER_RGB = 0, 1


def load():
    lib = ctypes.CDLL(_LIB)
    ci, cu32, cvp, cc = (ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p,
                         ctypes.c_char_p)
    pi, pu32 = ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint32)

    # buttons
    lib.bt_new.restype = cvp
    lib.bt_new.argtypes = [ci]
    lib.bt_free.argtypes = [cvp]
    lib.bt_set_debounce.argtypes = [cvp, ci]
    lib.bt_update.restype = ci
    lib.bt_update.argtypes = [cvp, ci, ci, cu32, pi, pi, ci]
    lib.bt_pressed.restype = ci
    lib.bt_pressed.argtypes = [cvp, ci]
    lib.bt_count.restype = ci

    # rings
    lib.rg_new.restype = cvp
    lib.rg_new.argtypes = [ci, ci]
    lib.rg_free.argtypes = [cvp]
    lib.rg_set.restype = ci
    lib.rg_set.argtypes = [cvp, ci, ci, ci, ci, ci]
    lib.rg_scale.restype = ci
    lib.rg_scale.argtypes = [ci, ci]
    lib.rg_pixel_word.restype = cu32
    lib.rg_pixel_word.argtypes = [cvp, ci, ci]
    lib.rg_render.restype = ci
    lib.rg_render.argtypes = [cvp, ci, ci, pu32, ci]
    lib.rg_dirty.restype = ci
    lib.rg_dirty.argtypes = [cvp, ci]
    lib.rg_clear_dirty.argtypes = [cvp, ci]
    lib.rg_count.restype = ci

    # protocol
    lib.pp_parse.restype = ci
    lib.pp_parse.argtypes = [cc, pi, pi, pi, pi, pi, pi, pi, pi]
    lib.pf_btn.restype = ci
    lib.pf_btn.argtypes = [cc, ci, ci, ci, cu32]
    lib.pf_hello.restype = ci
    lib.pf_hello.argtypes = [cc, ci, cc, ci, ci, ci, ci, cc]
    lib.pf_ack.restype = ci
    lib.pf_ack.argtypes = [cc, ci, cc]
    lib.pf_err.restype = ci
    lib.pf_err.argtypes = [cc, ci, cc]
    return lib


class Buttons:
    """Wraps a buttons_t; feed (raw0, raw1) levels at now_ms, get edge events."""

    def __init__(self, lib, debounce_ms=30):
        self.lib = lib
        self.n = lib.bt_count()
        self.h = lib.bt_new(debounce_ms)

    def update(self, raw, now_ms, max_events=8):
        """raw: sequence of two truthy/falsy levels. Returns [(id, pressed)]."""
        r0, r1 = (int(bool(v)) for v in raw)
        ids = (ctypes.c_int * max_events)()
        prs = (ctypes.c_int * max_events)()
        n = self.lib.bt_update(self.h, r0, r1, now_ms, ids, prs, max_events)
        return [(ids[i], bool(prs[i])) for i in range(n)]

    def pressed(self, idx):
        return bool(self.lib.bt_pressed(self.h, idx))

    def set_debounce(self, debounce_ms):
        self.lib.bt_set_debounce(self.h, debounce_ms)

    def free(self):
        self.lib.bt_free(self.h)


class Rings:
    """Wraps a rings_t (two rings with independent LED counts)."""

    def __init__(self, lib, nleds=(16, 16)):
        self.lib = lib
        self.nleds = tuple(nleds)
        self.h = lib.rg_new(self.nleds[0], self.nleds[1])

    def set(self, idx, r=-1, g=-1, b=-1, brightness=-1):
        return bool(self.lib.rg_set(self.h, idx, r, g, b, brightness))

    def pixel_word(self, idx, order=ORDER_GRB):
        return self.lib.rg_pixel_word(self.h, idx, order)

    def render(self, idx, order=ORDER_GRB, max_words=None):
        """Returns the rendered word list, or None if rejected (-1 from C)."""
        if max_words is None:
            max_words = max(self.nleds)
        words = (ctypes.c_uint32 * max(max_words, 1))()
        n = self.lib.rg_render(self.h, idx, order, words, max_words)
        if n < 0:
            return None
        return [words[i] for i in range(n)]

    def dirty(self, idx):
        return bool(self.lib.rg_dirty(self.h, idx))

    def clear_dirty(self, idx):
        self.lib.rg_clear_dirty(self.h, idx)

    def free(self):
        self.lib.rg_free(self.h)


def scale(lib, c, brightness):
    """rings_scale exposed directly: (c*brightness+127)/255 round-to-nearest."""
    return lib.rg_scale(c, brightness)


def parse_cmd(lib, line):
    vals = [ctypes.c_int() for _ in range(8)]
    found = lib.pp_parse(line.encode(), *(ctypes.byref(v) for v in vals))
    t, id_, r, g, b, br, on, deb = (v.value for v in vals)
    return {
        "found": bool(found), "type": t, "id": id_,
        "r": r, "g": g, "b": b, "brightness": br,
        "on": on, "debounce_ms": deb,
    }


def fmt_btn(lib, id_, pressed, ms, bufn=128):
    b = ctypes.create_string_buffer(bufn)
    rc = lib.pf_btn(b, bufn, id_, int(bool(pressed)), ms)
    return rc, b.value.decode()

def fmt_hello(lib, fw, nleds, pressed, ip, bufn=160):
    b = ctypes.create_string_buffer(bufn)
    rc = lib.pf_hello(b, bufn, fw.encode(), nleds[0], nleds[1],
                      int(bool(pressed[0])), int(bool(pressed[1])), ip.encode())
    return rc, b.value.decode()

def fmt_ack(lib, cmd, bufn=128):
    b = ctypes.create_string_buffer(bufn)
    rc = lib.pf_ack(b, bufn, cmd.encode())
    return rc, b.value.decode()

def fmt_err(lib, msg, bufn=128):
    b = ctypes.create_string_buffer(bufn)
    rc = lib.pf_err(b, bufn, msg.encode())
    return rc, b.value.decode()
