#!/usr/bin/env python3
"""Serial monitor for the RP2040-ETH board.

Auto-finds the Pico CDC port (USB VID 2e8a) so it won't grab unrelated ttyACM
devices, and asserts DTR so the Pico SDK USB-stdio actually emits output.

Usage: tools/monitor.py [--port /dev/ttyACMx] [--seconds N]
"""
import argparse
import sys
import time

import serial
from serial.tools import list_ports

PICO_VID = 0x2E8A


def find_port() -> str | None:
    for p in list_ports.comports():
        if (p.vid or 0) == PICO_VID:
            return p.device
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="serial port (default: auto-detect VID 2e8a)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=0, help="0 = run until Ctrl-C")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        print("No RP2040 (VID 2e8a) serial port found.", file=sys.stderr)
        return 1

    s = serial.Serial()
    s.port, s.baudrate = port, args.baud
    s.dtr = s.rts = True
    s.timeout = 0.2  # per-read timeout so sparse output never blocks past --seconds
    s.open()
    print(f"[monitor] {port} @ {args.baud} (DTR asserted) — Ctrl-C to quit")

    end = time.time() + args.seconds if args.seconds else None
    try:
        while end is None or time.time() < end:
            data = s.read(256)
            if data:
                sys.stdout.write(data.decode(errors="replace"))
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
