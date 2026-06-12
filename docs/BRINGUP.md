# Bring-up plan

Hardware verification checklist for the panel build (Waveshare RP2040-ETH + 2 buttons +
2× 16-LED WS2812 rings), wired per [`DESIGN.md`](DESIGN.md). **Not yet performed** —
each step below has an empty result slot to fill in on the bench. The board-level
gotchas at the bottom are carried over from the keypad project (same board) and apply
as-is.

Tooling: `tools/provision.sh` (one-time USB install), `tools/monitor.py` (serial),
`tools/ota_flash.py` (Ethernet updates), `tools/panel_live.py` (live events +
interactive commands), `tools/test.sh` / `tools/test_ota.sh` (host tests).

## 1. Provision over USB ☐
Hold **BOOTSEL** while plugging in USB (blank board), then:
```bash
cmake -S . -B build && cmake --build build -j
tools/provision.sh        # bootloader -> 0x10000000, panel -> 0x10040000, reboot
```
Expect: both loads succeed, board reboots, onboard LED goes **blue** (booting) then
green/amber flashing.

**Result:** _pending_

## 2. Serial boot banner ☐
Attach the monitor **before** reset (USB-CDC drops early output otherwise — see
gotchas), then tap RESET:
```bash
tools/monitor.py
```
Expect:
```
=== rp2040-eth-panel v1.0.0 (CH9120) ===
[net] ...
[main] panel up: buttons GP4/GP5, lamp GP6, rings GP2/GP3 (16/16 LEDs)
```

**Result:** _pending_

## 3. RING_SELFTEST — color-order check ☐
```bash
cmake -B build -DRING_SELFTEST=1 && cmake --build build -j && tools/flash.sh --no-build
```
Both rings cycle **RED 1 s → GREEN 2 s → BLUE 4 s**; serial prints the intended color.
Verify the *dwell time* matches the *seen* color on **both** rings (a GRB ring driven
as RGB shows green during the 1 s phase). If swapped, flip `RING_COLOR_ORDER_GRB` in
`src/config.h`. Note: the onboard GP25 status LED is RGB-order by design — judge only
the external rings.

**Result (ring 1):** _pending_
**Result (ring 2):** _pending_

## 4. Button + lamp bench check (still RING_SELFTEST) ☐
With the self-test build still flashed: press each button, watch serial echo raw edges
(`[ringtest] button 1 raw DOWN/UP`); the lamp must follow button 1. Confirms wiring
(GP4/GP5 to GND, pull-ups working, no inversion) and the GP6 lamp drive (and its
transistor stage, if fitted) before networking is in play.

**Result (button 1 / lamp):** _pending_
**Result (button 2):** _pending_

## 5. DHCP + status-LED octet ☐
Reflash the normal build (`cmake -B build -DRING_SELFTEST=0 && cmake --build build -j
&& tools/flash.sh --no-build`). With the Ethernet cable in a DHCP LAN: serial shows the
leased IP; the onboard WS2812 flashes the IP's **last octet** digit-by-digit (each
digit = that many short pulses, `0` = one long pulse) in **green** (DHCP). Remember the
color reflects the **configured mode**, not link state — green with no cable is
expected.

**Result (IP / octet match):** _pending_

## 6. panel_live — events + commands over Ethernet ☐
```bash
tools/panel_live.py <device-ip>
```
- Connect → a `hello` line arrives with fw/rings/pressed state.
- Press/release both buttons → `btn` down/up events with sane `ms` deltas.
- Send ring commands (each → `{"t":"ack","cmd":"ring"}`): ring 1 red, ring 2 blue,
  brightness-only change (color must hold — absent fields keep current).
- `lamp on/off` → button 1's illumination follows.
- `config debounce_ms=100` → ack; verify a light tap is now filtered.
- Disconnect/reconnect → fresh `hello`; rings hold their state (no flash persistence,
  but no reset either — state lives until power-off).

**Result:** _pending_

## 7. OTA cycle ☐
```bash
cmake --build build -j
tools/ota_flash.py --host <device-ip> build/panel.bin
```
Expect the full no-touch cycle on the recovery serial trace: SYNC → BEGIN (CRC match)
→ DATA → END verify match → `boot_state written` → DONE → reboot into the pushed image
→ `app confirmed healthy`. Then run at least one more push to prove repeatability, and
one interrupted push (yank Ethernet mid-DATA) to confirm the bootloader stays in
recovery and a re-push succeeds. See [`OTA.md`](OTA.md).

**Result:** _pending_

## 8. ROS 2 driver smoke ☐
On a Humble host (`ros2/panel_driver`, `host:=<device-ip>`):
- `~/button1/pressed`, `~/button2/pressed` publish on press/release; a late subscriber
  gets the latched last value.
- Publish `ColorRGBA` to `~/ring1/color` / `~/ring2/color` — **set `a`!** (`a` defaults
  to 0 = brightness 0 = dark).
- `~/button1/light` toggles the lamp.
- Restart the device mid-session → driver reconnects (`reconnect_period`) and re-sends
  desired state; rings return to the commanded colors without re-publishing.
- Confirm `panel_live.py` is **not** attached while the driver runs (single TCP client).

**Result:** _pending_

## Board-level field gotchas (carried over from the keypad bring-up — same board)
- **Liveness = TCP connect to port 5005, never ping.** The CH9120 answers ICMP itself,
  independent of the RP2040 — a dead app still pings.
- `picotool reboot` is a **no-op without `-f`** when a USB serial connection is present.
- RP2040 USB-CDC drops stdout written before a host opens the port with **DTR
  asserted**, and the app is silent when idle — use `tools/monitor.py` (asserts DTR)
  attached before reset to catch the boot banner.
- The CH9120 is a **single-client** TCP server — a second concurrent socket (e.g.
  `panel_live.py` alongside the ROS driver, or a stray `nc`) wedges the bridge.
- A sourced ROS environment puts broken pytest plugins on the path; the test scripts
  run with `PYTHONPATH=` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (`tools/test.sh`).
- CH9120 config baud is fixed at 9600; the data path runs at 115200. The leased IP is
  read back from the CH9120 (cmd `0x61`) for the LED octet + logging.
- No link/DHCP status is readable by the RP2040 (the CH9120 `LINK` pin drives the RJ45
  LEDs); the status LED shows the **configured** IP mode and a possibly cached IP.
