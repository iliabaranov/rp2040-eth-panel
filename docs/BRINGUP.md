# Bring-up record

Hardware verification for the panel build (Waveshare RP2040-ETH + 2 buttons + 2× 16-LED
WS2812 rings), wired per [`DESIGN.md`](DESIGN.md).

**Status: brought up and verified on hardware 2026-06-12.** Device on DHCP at
**192.0.2.50** (MAC `AA:BB:CC:12:34:56`), TCP server on port 5005. Currently running
**v1.0.2**, deployed entirely over Ethernet (OTA). Results below; a few formal sub-steps
were not separately run and are noted as such.

Tooling: `tools/provision.sh` (one-time USB install), `tools/monitor.py` (serial),
`tools/ota_flash.py` (Ethernet updates), `tools/panel_live.py` (live events +
interactive commands), `tools/test.sh` / `tools/test_ota.sh` (host tests).

Build environment on the dev machine (no system Pico install):
```bash
export PICO_SDK_PATH=$HOME/pico/pico-sdk
export PATH=$HOME/.local/bin:$HOME/pico/xpack-arm-none-eabi-gcc-13.2.1-1.1/bin:$PATH
```
A `udev` rule `/etc/udev/rules.d/99-picotool.rules` (MODE 0666, VID 2e8a) grants non-root
USB access; otherwise `picotool` needs `sudo`.

## 1. Provision over USB ✅
`tools/provision.sh` loaded bootloader → `0x10000000` and panel → `0x10040000`, board
rebooted. Both flash writes hit 100%, exit 0.

**Result:** PASS (2026-06-11).

## 2. Serial boot banner ✅
Captured by resetting with `tools/monitor.py`-style capture attached (banner prints once
~1.5 s after reset; steady state is silent except `[btn]` lines):
```
=== rp2040-eth-panel v1.0.0 (CH9120) ===
[net] CH9120 mode=0 ipmode=DHCP port=5005
[net] MAC AA:BB:CC:12:34:56
[net] IP 192.0.2.50  (connect: tcp 192.0.2.50:5005)
[main] panel up: buttons GP4/GP5, lamp GP6, rings GP2/GP3 (16/16 LEDs)
```
Note: the Pico enumerates as `/dev/ttyACM1` here (`/dev/ttyACM0` is an unrelated 1a86
device) — match by USB VID 2e8a.

**Result:** PASS.

## 3. RING_SELFTEST — color-order check ⚠️ (not formally run)
Not run as the formal `-DRING_SELFTEST=1` dwell-time check. Rings were instead verified
live via ROS `ColorRGBA` commands (acked by device, colors confirmed by operator), so the
default `RING_COLOR_ORDER_GRB=1` is correct for these rings in practice. If a ring ever
shows wrong colors, run the formal self-test and flip the macro.

**Result:** rings functional (colors correct via commands); formal self-test not separately run.

## 4. Button + lamp bench check ✅
Both buttons produce clean events; the lamp (GP6) and both rings respond to commands.
Raw device stream during presses:
```
{"t":"btn","id":1,"e":"down"} / {"e":"up"}      ← button 1
{"t":"btn","id":2,"e":"down"} / {"e":"up"}      ← button 2
```
Confirms GP4/GP5 → GND wiring, software pull-ups, active-low read (no inversion), and the
GP6 lamp output.

**Result:** PASS (both buttons + lamp).

## 5. DHCP + status-LED octet ✅ (octet not visually checked)
DHCP lease `192.0.2.50` confirmed via the serial banner. The onboard WS2812 octet
flash was not visually inspected, but the IP read-back and TCP reachability confirm
networking. Color reflects configured mode (green = DHCP), not link state.

**Result:** PASS (DHCP/IP); LED octet not separately observed.

## 6. panel_live / protocol over Ethernet ✅
Over TCP to `:5005`: `hello` on connect; `ping`/`ring`/`lamp` → matching `ack`; invalid
ring id → `{"t":"err","msg":"bad ring cmd"}`; unknown verb → `{"t":"err","msg":"unknown cmd"}`.
Hello is re-sent on every reconnect. (`config debounce_ms` runtime change not separately
exercised; covered by host tests.)

**Result:** PASS.

## 7. OTA cycle ✅ (interrupted-push covered by sim, not on hardware)
Two full no-touch Ethernet updates verified end-to-end:
- v1.0.0 → **v1.0.1** (USB still attached): 45684 B streamed, CRC-verified, rebooted.
- v1.0.1 → **v1.0.2** (USB **disconnected**, Ethernet-only): same, confirmed via `hello`
  reporting `fw=1.0.2`.
Each rebooted into the new image on the same IP and confirmed healthy (no revert to
recovery). The interrupted/fault-injected path was not exercised on hardware but is the
job of `tools/test_ota.sh` (7/7 pass: stale bytes, mid-transfer resets, byte loss).

**Result:** PASS (OTA over Ethernet, USB-free).

## 8. ROS 2 driver smoke ✅
`ros2/panel_driver` (Humble, `host:=192.0.2.50`): connected, logged `hello fw=1.0.2`,
both `~/button1/pressed` and `~/button2/pressed` published `true`/`false` on press/release
(latched initial state from hello); `ColorRGBA` ring commands and `Bool` lamp commands
acked by the device. The standalone example (`examples/standalone_panel_driver.py`) was
also verified after fixing its socket-timeout bug (see commit history).

**Result:** PASS (package driver + standalone example).

## Host test suites (no hardware) ✅
- `tools/test.sh` → 34 passed (buttons / rings / protocol pure logic via ctypes).
- `tools/test_ota.sh` → 7 passed (OTA transport fault-injection, ~5 min).
- `ros2/panel_driver` pytest → 15 passed (pure protocol helpers).

## Board-level field gotchas (carried over from the keypad bring-up — same board)
- **Liveness = TCP connect to port 5005, never ping.** The CH9120 answers ICMP itself,
  independent of the RP2040 — a dead app still pings.
- **Single TCP client.** A second concurrent connection (a stray `panel_live.py`, `nc`,
  or a *leftover* driver process) wedges the bridge; a new driver then silently fails to
  connect and publishes nothing. Check `ps aux | grep panel` / `ros2 node list`. NOTE: a
  backgrounded `ros2 run` that is SIGTERM'd can leave its node child alive holding the
  socket — `kill -9` the PID. Foreground Ctrl-C shuts down cleanly.
- `picotool reboot` is a **no-op without `-f`** when a USB serial connection is present.
- RP2040 USB-CDC drops stdout written before a host opens the port with **DTR asserted**,
  and the app is silent when idle — attach `tools/monitor.py` (asserts DTR) before reset.
- The standalone example publishes **only on a press** (no latched startup state), so
  `ros2 topic echo` stays quiet until you actually press. Its topics are plain
  (`/button1_pressed`, …); the package driver's are namespaced (`/panel_driver/button1/pressed`).
- A sourced ROS environment puts broken pytest plugins on the path; the test scripts run
  with `PYTHONPATH=` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (`tools/test.sh`).
- CH9120 config baud is fixed at 9600; the data path runs at 115200. The leased IP is read
  back from the CH9120 (cmd `0x61`) for the LED octet + logging.
- No link/DHCP status is readable by the RP2040 (the CH9120 `LINK` pin drives the RJ45
  LEDs); the status LED shows the **configured** IP mode and a possibly cached IP.
