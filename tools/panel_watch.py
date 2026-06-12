#!/usr/bin/env python3
"""Watch panel button presses over USB serial and print them live.

The firmware prints '[btn] 1 down' / '[btn] 2 up' lines on USB serial (see
src/main.c). This auto-detects the board (USB VID 2e8a), parses those lines,
and prints friendly timestamped rows:

    14:02:31   btn 1   ▼ down
    14:02:31   btn 1   ▲ up

Requires pyserial (the only non-stdlib dependency):
    python3 -m venv .venv && . .venv/bin/activate && pip install pyserial

Usage:
    tools/panel_watch.py                  # auto-detect the Pico CDC port
    tools/panel_watch.py --port /dev/ttyACM2
    tools/panel_watch.py --raw            # pass through ALL serial output
"""
import argparse
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None

PICO_VID = 0x2E8A
BTN_RE = re.compile(r"\[btn\]\s+([12])\s+(down|up)")
EDGE_GLYPH = {"down": "▼ down", "up": "▲ up"}


def find_port():
    for p in list_ports.comports():
        if (p.vid or 0) == PICO_VID:
            return p.device
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Watch panel button events over USB serial.")
    ap.add_argument("--port", help="serial port (default: auto-detect VID 2e8a)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--raw", action="store_true",
                    help="pass through all serial output instead of btn rows")
    args = ap.parse_args()

    if serial is None:
        print("panel_watch.py needs pyserial. Install it in a venv:\n"
              "    python3 -m venv .venv && . .venv/bin/activate && "
              "pip install pyserial", file=sys.stderr)
        return 1

    port = args.port or find_port()
    if not port:
        print("No RP2040 (VID 2e8a) serial port found. Is the board plugged in "
              "and running the app?", file=sys.stderr)
        return 1

    s = serial.Serial()
    s.port, s.baudrate = port, args.baud
    s.dtr = s.rts = True            # Pico SDK USB stdio emits nothing without DTR
    s.timeout = 0.2
    s.open()
    print(f"[panel_watch] {port} @ {args.baud} — press buttons, Ctrl-C to quit\n",
          flush=True)

    buf = b""
    try:
        while True:
            data = s.read(256)
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").rstrip()
                if args.raw:
                    print("  " + text, flush=True)
                    continue
                m = BTN_RE.search(text)
                if not m:
                    continue
                bid, edge = m.group(1), m.group(2)
                print(f"  {time.strftime('%H:%M:%S')}   btn {bid}   "
                      f"{EDGE_GLYPH[edge]}", flush=True)
    except KeyboardInterrupt:
        pass
    except serial.SerialException as e:
        print(f"\n[panel_watch] serial error: {e} (board unplugged?)",
              file=sys.stderr)
        return 1
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
