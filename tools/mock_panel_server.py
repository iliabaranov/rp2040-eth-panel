#!/usr/bin/env python3
"""Mock panel device for testing the ROS 2 driver / panel_live without hardware.

Bidirectional, unlike the keypad mock: speaks the firmware's line-delimited JSON
protocol on both directions. On client connect it sends a proper hello (with the
simulated pressed states), then periodically emits btn down/up pairs cycling
buttons 1 and 2. Inbound ring/lamp/config/ping/hello/ota commands are validated and
acked/erred exactly as src/main.c + src/protocol/protocol.c would; state changes
are printed to stdout.

Like the real device (CH9120 bridge), it serves a SINGLE client at a time; on
disconnect it accepts the next. {"cmd":"ota"} is acked, then the connection is
dropped, state reset, and after a brief "reboot" the next connect gets a fresh
hello — that exercises driver resync.

Quick start:
    tools/mock_panel_server.py                       # 127.0.0.1:5005, btn pair every 3 s
    tools/mock_panel_server.py --port 5557 --period 1.5
    tools/panel_live.py 127.0.0.1 --port 5557        # in another terminal
"""
import argparse
import json
import select
import socket
import time

FW = "mock"
RING_LEDS = [16, 16]
BTN_HOLD_S = 0.15  # down→up gap within one simulated press


class PanelState:
    """Simulated device state — mirrors what a reboot resets (rings off,
    brightness 255, lamp off, debounce 30 ms)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.rings = [{"r": 0, "g": 0, "b": 0, "brightness": 255} for _ in range(2)]
        self.lamp = False
        self.debounce_ms = 30
        self.pressed = [False, False]


def fmt_ack(cmd):
    return '{"t":"ack","cmd":"%s"}\n' % cmd


def fmt_err(msg):
    return '{"t":"err","msg":"%s"}\n' % msg


def fmt_hello(state):
    return json.dumps({"t": "hello", "fw": FW, "buttons": 2, "rings": RING_LEDS,
                       "pressed": list(state.pressed), "ip": "127.0.0.1"},
                      separators=(",", ":")) + "\n"


def fmt_btn(bid, pressed, ms):
    return ('{"t":"btn","id":%d,"e":"%s","ms":%d}\n'
            % (bid, "down" if pressed else "up", ms))


def _as_int(v):
    """Firmware get_int(): only a bare integer counts; anything else is 'absent'."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def process(state, line):
    """Handle one inbound line; returns (reply_line, is_ota). Mirrors dispatch()
    in src/main.c, including the exact ack/err strings."""
    if len(line) > 255:
        return fmt_err("line too long"), False  # firmware linebuf is 256
    try:
        obj = json.loads(line)
    except ValueError:
        obj = None
    cmd = obj.get("cmd") if isinstance(obj, dict) else None
    if not isinstance(cmd, str):
        return fmt_err("no cmd"), False

    if cmd == "ring":
        rid = _as_int(obj.get("id"))
        if rid is None or not 1 <= rid <= 2:
            return fmt_err("bad ring cmd"), False
        vals = {}
        for k in ("r", "g", "b", "brightness"):
            v = _as_int(obj.get(k))
            if v is None:
                continue  # absent = keep current (firmware -1)
            if not 0 <= v <= 255:
                return fmt_err("bad ring cmd"), False
            vals[k] = v
        st = state.rings[rid - 1]
        st.update(vals)
        print(f"ring {rid} -> rgb({st['r']},{st['g']},{st['b']}) "
              f"br={st['brightness']}", flush=True)
        return fmt_ack("ring"), False

    if cmd == "lamp":
        on = obj.get("on")
        if isinstance(on, bool):
            val = on
        elif on in (0, 1):
            val = bool(on)  # firmware get_bool also accepts bare 1/0
        else:
            return fmt_err("bad lamp cmd"), False
        state.lamp = val
        print(f"lamp -> {'ON' if val else 'OFF'}", flush=True)
        return fmt_ack("lamp"), False

    if cmd == "config":
        d = _as_int(obj.get("debounce_ms"))
        if d is None or not 1 <= d <= 1000:
            return fmt_err("bad debounce_ms"), False
        state.debounce_ms = d
        print(f"debounce -> {d} ms", flush=True)
        return fmt_ack("config"), False

    if cmd == "ping":
        return fmt_ack("ping"), False

    if cmd == "hello":
        return fmt_hello(state), False  # reply IS the hello line, no ack

    if cmd == "ota":
        return fmt_ack("ota"), True

    return fmt_err("unknown cmd"), False


def serve_client(conn, state, period, t0):
    """One client session. Returns 'ota' if the client requested a simulated
    reboot; raises ConnectionError/OSError on disconnect."""
    conn.sendall(fmt_hello(state).encode())
    next_btn = time.monotonic() + min(1.0, period)  # first pair comes quickly
    btn_idx = 0  # cycles buttons 1, 2, 1, 2, ...
    phase_down = True
    buf = b""
    while True:
        now = time.monotonic()
        if now >= next_btn:
            bid = (btn_idx % 2) + 1
            state.pressed[bid - 1] = phase_down
            conn.sendall(fmt_btn(bid, phase_down, int((now - t0) * 1000)).encode())
            print(f"btn {bid} {'down' if phase_down else 'up'}", flush=True)
            if phase_down:
                next_btn = now + BTN_HOLD_S
            else:
                btn_idx += 1
                next_btn = now + period
            phase_down = not phase_down

        timeout = max(0.0, min(0.25, next_btn - time.monotonic()))
        readable, _, _ = select.select([conn], [], [], timeout)
        if not readable:
            continue
        data = conn.recv(1024)
        if not data:
            raise ConnectionError("client closed the connection")
        buf += data
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.strip().decode(errors="replace")
            if not line:
                continue
            reply, is_ota = process(state, line)
            conn.sendall(reply.encode())
            if is_ota:
                time.sleep(0.05)  # firmware: let the ack drain through the CH9120
                return "ota"


def main():
    ap = argparse.ArgumentParser(
        description="Mock rp2040-eth-panel TCP device (bidirectional).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--period", type=float, default=3.0,
                    help="seconds between simulated btn down/up pairs (default 3)")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(1)
    print(f"mock panel server on {args.host}:{args.port} — single client, "
          f"btn pair every {args.period}s (Ctrl-C to quit)", flush=True)

    state = PanelState()
    t0 = time.monotonic()
    try:
        while True:
            conn, addr = srv.accept()
            print(f"client connected: {addr[0]}:{addr[1]}", flush=True)
            result = None
            try:
                result = serve_client(conn, state, args.period, t0)
            except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                print(f"client disconnected ({e})", flush=True)
            finally:
                conn.close()
            if result == "ota":
                print("ota -> dropping connection, simulated reboot "
                      "(state reset)...", flush=True)
                state.reset()
                time.sleep(1.0)  # "reboot"; next accept sends a fresh hello
    except KeyboardInterrupt:
        print("\nmock panel server: bye", flush=True)
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
