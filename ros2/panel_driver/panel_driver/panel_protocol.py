"""Pure protocol helpers for the RP2040-ETH panel driver (no rclpy dependency).

Mirrors src/protocol/protocol.h in the firmware: line-delimited JSON, one
object per '\n'-terminated line, both directions.

Device -> host (parse_event):
    {"t":"hello","fw":"1.0.0","buttons":2,"rings":[16,16],"pressed":[false,false],"ip":"..."}
    {"t":"btn","id":1,"e":"down","ms":123456}
    {"t":"ack","cmd":"ring"}
    {"t":"err","msg":"bad ring id"}

Host -> device (formatters; every line ends with '\n'):
    {"cmd":"ring","id":1,"r":255,"g":64,"b":0,"brightness":128}
    {"cmd":"lamp","on":true}
    {"cmd":"hello"}   (request the hello line; the reply is the hello event)

Unit-testable standalone: test/test_panel_protocol.py imports this module with
no ROS graph or environment.
"""
from __future__ import annotations

import json


def parse_event(line: str) -> dict | None:
    """Parse one device->host JSON line; return a normalized event dict or None.

    Returns (by "t"):
      btn   -> {"t":"btn","id":int,"e":"down"|"up","ms":int|None}
      hello -> {"t":"hello","fw":str|None,"buttons":int|None,"rings":list,
                "pressed":[bool,...],"ip":str|None}
      ack   -> {"t":"ack","cmd":str|None}
      err   -> {"t":"err","msg":str}
    None for blank lines, malformed JSON, unknown "t", or btn events missing
    a valid id/edge.
    """
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    t = obj.get("t")
    if t == "btn":
        bid, edge = obj.get("id"), obj.get("e")
        if not isinstance(bid, int) or isinstance(bid, bool):
            return None
        if edge not in ("down", "up"):
            return None
        ms = obj.get("ms")
        return {"t": "btn", "id": bid, "e": edge,
                "ms": ms if isinstance(ms, int) else None}
    if t == "hello":
        pressed = obj.get("pressed")
        if not isinstance(pressed, list):
            pressed = []
        rings = obj.get("rings")
        if not isinstance(rings, list):
            rings = []
        return {
            "t": "hello",
            "fw": str(obj["fw"]) if "fw" in obj else None,
            "buttons": obj.get("buttons"),
            "rings": rings,
            "pressed": [bool(p) for p in pressed],
            "ip": str(obj["ip"]) if "ip" in obj else None,
        }
    if t == "ack":
        cmd = obj.get("cmd")
        return {"t": "ack", "cmd": str(cmd) if cmd is not None else None}
    if t == "err":
        return {"t": "err", "msg": str(obj.get("msg", ""))}
    return None


def _clamp8(v) -> int:
    """Clamp a numeric value to an int in 0..255."""
    return max(0, min(255, int(round(float(v)))))


def fmt_ring_cmd(ring_id: int, r: int, g: int, b: int, brightness: int) -> str:
    """Format a host->device ring command line (trailing '\n' included).

    Color/brightness values are clamped to 0..255. Field order matches the
    firmware's documented protocol exactly.
    """
    return ('{"cmd":"ring","id":%d,"r":%d,"g":%d,"b":%d,"brightness":%d}\n'
            % (int(ring_id), _clamp8(r), _clamp8(g), _clamp8(b),
               _clamp8(brightness)))


def fmt_lamp_cmd(on: bool) -> str:
    """Format a host->device lamp command line (trailing '\n' included)."""
    return '{"cmd":"lamp","on":%s}\n' % ("true" if on else "false")


def fmt_hello_cmd() -> str:
    """Format a host->device hello request line (trailing '\n' included).

    The device replies with the hello event line. Hosts must request the hello
    after connecting rather than waiting for the unsolicited one: some CH9120
    batches never assert the TCP-status pin that triggers it.
    """
    return '{"cmd":"hello"}\n'


def color_rgba_to_bytes(r: float, g: float, b: float,
                        a: float) -> tuple[int, int, int, int]:
    """Convert std_msgs/ColorRGBA floats (0..1) to device bytes (0..255).

    The alpha channel carries BRIGHTNESS: a=0.0 means the ring is OFF,
    a=1.0 is full brightness. ColorRGBA defaults a to 0.0, so senders MUST
    set it explicitly. Inputs are clamped to [0, 1] and scaled with round().
    """
    def to8(x: float) -> int:
        x = min(1.0, max(0.0, float(x)))
        return int(round(x * 255.0))

    return (to8(r), to8(g), to8(b), to8(a))
