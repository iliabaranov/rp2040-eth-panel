#!/usr/bin/env python3
"""Live panel console over Ethernet — watch button events and drive rings/lamp.

The device is a TCP server (port 5005, SINGLE client — the CH9120 bridge wedges
on a second socket) speaking line-delimited JSON. Device→host: hello on connect,
btn down/up events, ack/err replies. Host→device: ring/lamp/config/ping/ota.

This connects, prints events as friendly timestamped rows, and reads commands
from stdin concurrently so you can drive the panel interactively. Pure standard
library — no pyserial/ROS needed. Auto-reconnects every 2 s if the device
reboots or drops the link. If stdin closes (piped input ran out) it keeps
watching events.

Quick start:
    tools/panel_live.py 10.74.29.12            # the device's IP (serial / LED octet)
    tools/panel_live.py 10.74.29.12 --raw      # print raw JSON lines instead
    tools/panel_live.py 127.0.0.1 --port 5005  # against tools/mock_panel_server.py

Interactive commands (one per line on stdin):
    ring <id> <r> <g> <b> [brightness]    e.g. ring 1 255 0 0 200   (id 1..2, 0..255)
    lamp on|off                           button-1 illumination
    config <debounce_ms>                  1..1000
    ping
    ota                                   reboot into OTA recovery — device drops the link
    raw <json>                            send a raw JSON line verbatim
    help
    quit
"""
import argparse
import json
import os
import select
import socket
import sys
import time

EDGE_GLYPH = {"down": "▼ down", "up": "▲ up"}

HELP_TEXT = """\
  commands:
    ring <id> <r> <g> <b> [brightness]   set ring color (id 1..2, values 0..255)
    lamp on|off                          button-1 illumination lamp
    config <debounce_ms>                 set debounce (1..1000 ms)
    ping                                 round-trip check (expect ack)
    ota                                  reboot device into OTA recovery
    raw <json>                           send a raw JSON line as-is
    help                                 this text
    quit                                 exit\
"""


def _ts():
    return time.strftime("%H:%M:%S")


def show_event(line, raw):
    """Pretty-print one device→host JSON line (or pass through with --raw)."""
    text = line.decode(errors="replace")
    if raw:
        print("  " + text, flush=True)
        return
    try:
        ev = json.loads(text)
    except ValueError:
        print(f"  {_ts()}   ?          {text}", flush=True)
        return
    t = ev.get("t")
    if t == "hello":
        print(f"  {_ts()}   ● hello    fw={ev.get('fw')} buttons={ev.get('buttons')} "
              f"rings={ev.get('rings')} pressed={ev.get('pressed')} ip={ev.get('ip')}",
              flush=True)
    elif t == "btn":
        edge = ev.get("e", "")
        print(f"  {_ts()}   btn {ev.get('id')}      {EDGE_GLYPH.get(edge, edge)}"
              f"   (t+{ev.get('ms')}ms)", flush=True)
    elif t == "ack":
        print(f"  {_ts()}   ✓ ack      {ev.get('cmd')}", flush=True)
    elif t == "err":
        print(f"  {_ts()}   ✗ err      {ev.get('msg')}", flush=True)
    else:
        print(f"  {_ts()}   ?          {text}", flush=True)


class Quit(Exception):
    """Raised by the 'quit' command to leave the program."""


def _int_args(parts, lo=0, hi=255):
    vals = []
    for p in parts:
        v = int(p)  # ValueError handled by caller
        if not lo <= v <= hi:
            raise ValueError(f"{v} out of range {lo}..{hi}")
        vals.append(v)
    return vals


def build_command(line):
    """Translate one stdin line into a protocol JSON string (or None for local
    commands like help). Raises Quit on 'quit', ValueError on bad usage."""
    parts = line.split()
    verb = parts[0].lower()
    if verb in ("quit", "exit"):
        raise Quit()
    if verb == "help":
        print(HELP_TEXT, flush=True)
        return None
    if verb == "ring":
        if len(parts) not in (5, 6):
            raise ValueError("usage: ring <id> <r> <g> <b> [brightness]")
        rid = int(parts[1])
        r, g, b = _int_args(parts[2:5])
        cmd = {"cmd": "ring", "id": rid, "r": r, "g": g, "b": b}
        if len(parts) == 6:
            cmd["brightness"] = _int_args(parts[5:6])[0]
        return json.dumps(cmd, separators=(",", ":"))
    if verb == "lamp":
        if len(parts) != 2 or parts[1].lower() not in ("on", "off", "1", "0"):
            raise ValueError("usage: lamp on|off")
        return json.dumps({"cmd": "lamp", "on": parts[1].lower() in ("on", "1")},
                          separators=(",", ":"))
    if verb == "config":
        if len(parts) != 2:
            raise ValueError("usage: config <debounce_ms>")
        return json.dumps({"cmd": "config", "debounce_ms": int(parts[1])},
                          separators=(",", ":"))
    if verb == "ping":
        return '{"cmd":"ping"}'
    if verb == "ota":
        return '{"cmd":"ota"}'
    if verb == "raw":
        rest = line[len(parts[0]):].strip()
        if not rest:
            raise ValueError("usage: raw <json>")
        return rest
    raise ValueError(f"unknown command {verb!r} — type 'help'")


def handle_input_line(sock, line, raw):
    line = line.strip()
    if not line:
        return
    try:
        payload = build_command(line)
    except ValueError as e:
        print(f"  {_ts()}   ! local    {e}", flush=True)
        return
    if payload is None:
        return
    sock.sendall(payload.encode() + b"\n")
    if raw:
        print("> " + payload, flush=True)
    else:
        print(f"  {_ts()}   → send     {payload}", flush=True)


def session(host, port, raw, stdin_state):
    """One connection: select() on socket + stdin until the link drops."""
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(None)
        print(f"[panel_live] connected to {host}:{port} — type 'help' for commands, "
              f"Ctrl-C to quit\n", flush=True)
        netbuf = b""
        inbuf = b""
        while True:
            rlist = [sock]
            if stdin_state["open"]:
                rlist.append(0)  # stdin fd
            readable, _, _ = select.select(rlist, [], [])
            if sock in readable:
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("device closed the connection")
                netbuf += data
                while b"\n" in netbuf:
                    line, netbuf = netbuf.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        show_event(line, raw)
            if 0 in readable:
                data = os.read(0, 4096)
                if not data:
                    stdin_state["open"] = False
                    print("[panel_live] stdin closed — watching events only "
                          "(Ctrl-C to quit)", flush=True)
                    continue
                inbuf += data
                while b"\n" in inbuf:
                    line, inbuf = inbuf.split(b"\n", 1)
                    handle_input_line(sock, line.decode(errors="replace"), raw)


def main():
    ap = argparse.ArgumentParser(
        description="Live panel console: print btn/ack/err events, send commands.")
    ap.add_argument("host", help="device IP (shown on USB serial and the WS2812 octet)")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--raw", action="store_true",
                    help="print raw JSON lines instead of pretty rows")
    args = ap.parse_args()

    stdin_state = {"open": True}  # once stdin hits EOF it stays closed
    try:
        while True:
            try:
                session(args.host, args.port, args.raw, stdin_state)
            except (OSError, ConnectionError) as e:
                print(f"\n[panel_live] {e} — reconnecting in 2s (Ctrl-C to quit)...",
                      file=sys.stderr, flush=True)
                time.sleep(2)
    except Quit:
        print("[panel_live] bye", flush=True)
    except KeyboardInterrupt:
        print("\n[panel_live] bye", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
