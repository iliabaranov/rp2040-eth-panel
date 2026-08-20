# rp2040-eth-panel

Network-connected **two-button / dual-WS2812-ring operator panel** on a **Waveshare
RP2040-ETH** board. Debounces the buttons and streams press/release events over Ethernet
as line-delimited JSON; the host drives the two 16-LED rings and the illuminated
button's lamp over the same socket — with **robust firmware updates over Ethernet**
(no USB or physical access needed after the one-time install).

- **Board:** Waveshare RP2040-ETH (RP2040 + CH9120 UART↔Ethernet bridge; 4 MB flash)
- **Firmware:** C11 / Raspberry Pi Pico SDK 2.1.1
- **Network:** DHCP, TCP server on port 5005, line-delimited JSON
- **Inputs:** 2 momentary buttons (button 1 illuminated), 30 ms debounce (runtime-configurable)
- **Outputs:** 2× 16-LED WS2812 rings (color + brightness), button-1 lamp on/off (GP6)
- **OTA:** immutable bootloader + single app slot + network recovery (CRC32-verified)

The panel is a **host-commanded peripheral**: rings and lamp power up dark and the host
(normally the ROS 2 driver) re-sends desired state on every connect — see
[`docs/DESIGN.md`](docs/DESIGN.md) for why nothing is persisted to flash. Sibling
project of [`rp2040-eth-keypad`](../rp2040-eth-keypad) (same board, same OTA stack).

See [`docs/DESIGN.md`](docs/DESIGN.md), [`docs/OTA.md`](docs/OTA.md),
[`docs/BRINGUP.md`](docs/BRINGUP.md), and the CH9120/board datasheets in
[`docs/`](docs/).

## Repository layout
```
firmware/     the Pico SDK build (CMake root); COLCON_IGNORE keeps colcon out of it
  src/          application: net (CH9120), buttons, rings, status LED, protocol, ota
  bootloader/   immutable first-stage bootloader (boot select + OTA recovery receiver)
  linker/       app (0x10040000) and bootloader (0x10000000, 256 KB) memory maps
ros2/panel_driver/   ROS 2 (Humble) driver: button topics in, ring/lamp topics out
examples/     standalone single-file ROS 2 driver (run directly — no colcon build)
test/         pytest + ctypes tests for the pure logic (buttons/rings/protocol) + OTA sim
tools/        flash / monitor / OTA / provision / live & mock helpers
```

## Prerequisites
Pico SDK (`PICO_SDK_PATH` set), the ARM toolchain (`arm-none-eabi-gcc`), CMake, and
`picotool` **built with USB support** (needs `libusb-1.0-dev`; a `99-picotool.rules` udev
rule for VID `2e8a` enables non-root access). Python 3 + `pyserial` for the host tools.

On this machine the toolchain lives at:
```bash
export PICO_SDK_PATH=~/pico/pico-sdk
export PATH=~/pico/xpack-arm-none-eabi-gcc-13.2.1-1.1/bin:~/.local/bin:$PATH   # GCC 13.2 + picotool 2.1.1
```

## Build
```bash
cmake -S firmware -B build   # one-time configure
cmake --build build -j       # -> build/{bootloader,panel,apptest}.uf2 (+ .bin)
```

## Install (one time, over USB)
Flashes the immutable bootloader (`0x10000000`) + application (`0x10040000`). After this,
all firmware updates go over Ethernet.
```bash
tools/provision.sh          # forces BOOTSEL, loads both stages, reboots
```
If the board can't be reached (blank flash, no app), hold the **BOOTSEL** button while
plugging in USB, then run `tools/provision.sh`. On boot the WS2812 LED flashes the IP's
last octet (green = DHCP).

## Bench test (no network): RING_SELFTEST
```bash
cmake -S firmware -B build -DRING_SELFTEST=1 && cmake --build build -j && tools/flash.sh --no-build
```
Skips networking and cycles pure logical **RED 1 s → GREEN 2 s → BLUE 4 s** on both
rings — the distinct dwell times identify which channel is which, so a GRB/RGB swap is
obvious (fix via `RING_COLOR_ORDER_GRB` in `firmware/src/config.h`). Raw button edges echo on
USB serial and the lamp follows button 1, so the whole panel is verifiable with just
USB power. Rebuild without the flag for the normal firmware.

## Watch events / drive the panel live
Quickest way to confirm the panel works over Ethernet. Pure-Python stdlib, no ROS:
```bash
tools/panel_live.py <device-ip>      # e.g. tools/panel_live.py 10.74.29.13
```
Prints each button down/up as it happens **and** takes interactive ring/lamp commands
(e.g. set ring 1 red, lamp on) so both directions of the protocol are exercised from
one terminal. `tools/panel_watch.py` is the watch-only variant for passive logging. The
device IP is shown on USB serial and encoded by the WS2812 (last octet). (No hardware
yet? `tools/mock_panel_server.py` emits the same protocol on `127.0.0.1:5005`.)

> The CH9120 is a **single-client** TCP server — disconnect `panel_live.py` before
> starting the ROS driver (and vice versa); a second socket wedges the bridge.

## Update firmware over Ethernet (OTA)
```bash
cmake --build build -j                                  # build the new image
tools/ota_flash.py --host <device-ip> build/panel.bin
```
This asks the running app to reboot into recovery, streams the image in CRC-checked
chunks, verifies the whole image, and reboots into it — no USB, no buttons. A failed or
interrupted update can't brick the device: the immutable bootloader stays in network
recovery for a re-push (`--in-recovery` skips the app trigger).

The transfer is resilient to the CH9120's frameless byte-stream quirks: both ends
**resync to known token boundaries** (so stray/stale bytes from a dropped connection
can't desync the session), corrupt chunks are re-sent locally, and the whole flash
auto-retries on a fresh connection if the link blips (`--retries`, default 3). See
[`docs/OTA.md`](docs/OTA.md) → *Transport robustness*.

## Status LED (onboard WS2812, GP25)
| Color | Meaning |
|-------|---------|
| blue (solid) | app booted, bringing up the network |
| green, flashing digits | app running, **DHCP** mode (digits = IP's last octet) |
| amber, flashing digits | app running, **static** mode (digits = IP's last octet) |
| purple (solid) | bootloader recovery — waiting for / receiving an OTA |

> The color reflects the **configured IP mode**, not a live Ethernet link. The CH9120
> exposes no link/DHCP status to the RP2040 (its `LINK` pin drives the RJ45 jack LEDs,
> not a GPIO), and returns a cached IP even with no cable — so firmware can't detect
> "cable attached." Set the mode for your network via `NET_USE_DHCP` in `firmware/src/config.h`
> (no auto-fallback).

## ROS 2 driver (Humble)
[`ros2/panel_driver/`](ros2/panel_driver/) connects to the device's TCP/JSON server and
bridges it to topics:

| Topic | Type | Direction | Notes |
|-------|------|-----------|-------|
| `~/button1/pressed` | `std_msgs/Bool` | publish | latched (transient local) |
| `~/button2/pressed` | `std_msgs/Bool` | publish | latched (transient local) |
| `~/ring1/color` | `std_msgs/ColorRGBA` | subscribe | `a` = brightness 0..1 |
| `~/ring2/color` | `std_msgs/ColorRGBA` | subscribe | `a` = brightness 0..1 |
| `~/button1/light` | `std_msgs/Bool` | subscribe | illuminated button's lamp |

Parameters: `host`, `port` (default 5005), `reconnect_period`.

> **Warning:** `ColorRGBA.a` defaults to **0**, which means brightness 0 — a message
> with only `r/g/b` set shows nothing. Always set `a` (1.0 = full).

The driver owns desired state: it caches the last commanded ring colors and lamp state
and **re-sends them whenever the device reconnects** (every `hello` triggers this;
the driver waits ~1 s for the device's connect-time hello and requests one itself
if it doesn't arrive — it never fires on CH9120 batches whose TCPS status pin is
dead).

The driver also supervises the link itself: the CH9120 silently drops a displaced
client (no FIN/RST), which strands a naive client on a half-open socket. The driver
pings after 2 s of RX silence and declares the connection dead after 6 s without
**receiving** anything (`keepalive_period` / `liveness_timeout` parameters), then
reconnects and resyncs automatically — no manual restarts. Note this supervises but
does not repeal the single-client rule: two drivers pointed at one panel will
endlessly steal the slot from each other, visibly, in both logs. The firmware deliberately persists
nothing — see [`docs/DESIGN.md`](docs/DESIGN.md). Single TCP client only: stop
`panel_live.py` (and any other driver) before launching the driver.

### Standalone example (no build)
For a minimal, copy-pasteable starting point, [`examples/standalone_panel_driver.py`](examples/standalone_panel_driver.py)
is a ~100-line single-file driver you run directly — no colcon build, no package, no
launch file:
```bash
source /opt/ros/humble/setup.bash
python3 examples/standalone_panel_driver.py <device-ip>
ros2 topic echo /button1_pressed          # plain names: /button{1,2}_pressed, /ring{1,2}_color, /button1_light
```
It publishes only on a press (no latched startup state), so `echo` stays quiet until you
press. Use the `panel_driver` package above for production (auto-reconnect, desired-state
resync, latched state, clean shutdown).

## Tests
```bash
tools/test.sh      # fast: pure-logic host lib + pytest (buttons/rings/protocol)
tools/test_ota.sh  # OTA stress: real flasher vs. device+CH9120 simulator, fault-injected
```
`tools/test_ota.sh` runs hundreds of OTA pushes through a faithful CH9120-bridge
simulator with injected stale bytes, mid-transfer resets, and byte loss — the
regression guard for the transport-desync bug (multi-minute by design, no hardware).

## Recovery
- **App update failed / device in recovery:** re-run `tools/ota_flash.py` (it auto-detects
  recovery), or push with `--in-recovery`.
- **Device unresponsive:** press **RESET** (RUN button) to reboot into the last valid app.
- **Re-provision / bootloader update:** hold **BOOTSEL**, replug USB, run `tools/provision.sh`.
  USB BOOTSEL (mask ROM) is always available as the ultimate fallback.

## License
Apache License 2.0 — see [`LICENSE`](LICENSE).
