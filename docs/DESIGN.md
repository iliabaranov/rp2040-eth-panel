# RP2040-ETH Panel Controller — Design

Network-connected **two-button / dual-WS2812-ring operator panel** on a **Waveshare
RP2040-ETH** board (RP2040 + CH9120 UART↔Ethernet bridge). Debounces the buttons and
streams press/release events to a TCP client as line-delimited JSON; the host commands
the two LED rings and the illuminated button's lamp over the same socket. Firmware is
updated over Ethernet (no USB/physical access after the one-time install) — see
[`OTA.md`](OTA.md). Port of the `rp2040-eth-keypad` project to a different front-panel
peripheral set (same board, network layer, status LED, and OTA stack).

## Requirements (locked)

| Decision       | Choice                                                                  |
|----------------|--------------------------------------------------------------------------|
| Panel hardware | 2 momentary buttons (button 1 illuminated, lamp output) + 2× WS2812 rings (16 LEDs each) |
| MCU / board    | **Waveshare RP2040-ETH** (RP2040 + **CH9120** UART↔Ethernet bridge)      |
| Firmware stack | C11, Raspberry Pi Pico SDK 2.1.1 (CH9120 driven over UART1; no Ethernet lib) |
| Transport      | TCP **server** on the device, port 5005, single control client          |
| Wire format    | Line-delimited JSON (one object per `\n`-terminated line), both ways     |
| IP addressing  | **DHCP** by default (`NET_USE_DHCP`); static is a compile-time option. No auto-fallback — the CH9120 exposes no link/lease status the RP2040 can read, so the mode is chosen explicitly. |
| Host side      | ROS 2 (Humble) driver `ros2/panel_driver` owns desired ring/lamp state  |
| State          | **Nothing persisted to flash** — see *No flash persistence* below       |

## Hardware

### Buttons
- Two momentary buttons wired **to GND**, read with internal pull-ups → **active-low**.
  No external parts needed.
- Button 1 is an **illuminated** button; its lamp is driven separately from GP6.
- Debounce default **30 ms** (`DEBOUNCE_MS_DEFAULT`), runtime-overridable via the
  `config` command. The first sample after boot **seeds** the debouncer state without
  emitting an edge, so a button held during power-up doesn't fire a phantom event (its
  state still reaches the host in the `hello` line).

### WS2812 rings (2× 16 LEDs)
- **Power from 5 V** (header pin 1 = VBUS), not 3.3 V. Data line via a **~330 Ω series
  resistor** close to the first LED.
- 3.3 V data into a 5 V-powered ring usually works; if colors glitch or the first LED
  misbehaves, add a **level shifter** (e.g. 74AHCT125) on the data line.
- Put **~1000 µF** of bulk capacitance across each ring's power feed.
- **Power budget:** worst-case full-white is ~60 mA/LED → **≈960 mA per 16-LED ring at
  5 V** (~1.9 A both rings). Mind the USB/5 V supply budget; typical indicator colors at
  partial brightness draw far less.
- Color order is per-chain: standard WS2812B rings latch **GRB**
  (`RING_COLOR_ORDER_GRB=1` default); the board's **onboard GP25 LED anomalously
  latches RGB** (verified by self-test in the keypad project). See *WS2812 byte order*.

### Button-1 lamp (GP6)
GP6 is a plain on/off 3.3 V GPIO output. Driving the lamp directly is fine only for a
low-current 3.3 V LED (**≲10 mA**). If the illuminated button's lamp needs more
current, or runs at 5/12/24 V, use a **transistor/MOSFET low-side driver** (gate/base
from GP6 with a series resistor + pulldown, lamp supply to its own rail).

## Pin map (Waveshare RP2040-ETH)

Reserved by the CH9120 bridge (fixed by the board), do not reuse:

| Signal | GPIO | Notes                                   |
|--------|------|-----------------------------------------|
| UART1 TX → CH9120 RXD | GP20 | RP2040 transmits config/data   |
| UART1 RX ← CH9120 TXD | GP21 | RP2040 receives data           |
| CFG    | GP18 | LOW = config mode                       |
| RST    | GP19 | Active-low reset                        |
| TCPS   | GP17 | LOW = TCP peer connected                |

**Header reality (RP2040-ETH MINI):** the 24-pin header (P1) only breaks out
**GPIO0–9, 22, 26, 27, 28** (+ power/RUN). GP10–15 and GP25 are *not* on the header;
GP16–21 are the CH9120. Application pins are chosen from the broken-out set:

| Function | GPIO | Header pin | Notes |
|----------|------|-----------|-------|
| Ring 1 data | GP2 | 21 | via ~330 Ω series resistor |
| Ring 2 data | GP3 | 20 | via ~330 Ω series resistor |
| Button 1 | GP4 | 19 | illuminated button, to GND, internal pull-up (active-low) |
| Button 2 | GP5 | 18 | to GND, internal pull-up (active-low) |
| Lamp (button 1) | GP6 | 16 | plain on/off output, 3.3 V — see drive note above |
| Status LED | GP25 | — | onboard WS2812 (RGB byte order!) |

Power: **GND** on header pins 3/8/17/22; **VBUS 5 V** on header pin 1 (ring power and,
via a driver, the lamp supply).

### CH9120 networking
The RP2040 holds CFG low, sends config frames (`0x57 0xAB <cmd> <data>`) at 9600 baud to
set mode/IP/subnet/gateway/port and the data baud, commits (`0x0d` save, `0x0e`
execute+reset), releases CFG, and switches UART1 to 115200. Thereafter UART1 is a transparent pipe to
the TCP socket — the protocol layer just reads/writes bytes. `net_peer_connected()`
reflects the TCPS pin. See `src/net/net.c`.

## Software architecture

Clean separation: **pure logic** modules (no hardware, no SDK calls — host-testable)
behind thin **glue** that touches the SDK/GPIO/PIO/CH9120.

```
src/
  main.c                — super-loop: buttons -> events, dispatch commands, flush rings
  config.h              — compile-time defaults (pins, ring sizes, debounce, IP mode)
  buttons/
    buttons.h/.c        — PURE: per-button debounce + press/release edge events,
                          first-sample seeding (no phantom edge at boot)
    buttons_hw.c        — GLUE: GPIO init (pull-ups), raw active-low reads, lamp output
  rings/
    rings.h/.c          — PURE: per-ring color/brightness state, (c*brightness+127)/255
                          round-to-nearest scaling, GRB/RGB pixel-word packing, dirty flags
    rings_hw.c          — GLUE: PIO state machines, blocking FIFO pushes
  net/
    net.h/.c            — GLUE: CH9120 config over UART1 (mode/IP/port/baud), then
                          byte-stream read/write to the TCP socket; peer-connected pin
  protocol/
    protocol.h/.c       — PURE: JSON parse (commands) / format (events), schema
  status_led/           — onboard WS2812 (PIO): boot/mode/recovery indication
  ota/                  — flash layout, CRC32, boot-state, app-side update trigger
bootloader/             — immutable first stage: boot select + network OTA recovery
test/                   — pytest + ctypes against a host-built shared lib of the PURE
                          modules; OTA failure-injection suite (sim + real flasher)
```
The two-stage boot (immutable bootloader + single app slot) and the Ethernet update
protocol are documented separately in [`OTA.md`](OTA.md).

The pure modules take time as an argument (`now_ms`) and raw samples from the caller,
so debounce and rendering logic run identically on host and target.

### PIO allocation
One shared `ws2812` PIO program per block:

| PIO | SM | Output |
|-----|----|--------|
| pio0 | sm0 | onboard status LED, GP25 (RGB order) |
| pio1 | sm0 | ring 1, GP2 (GRB order) |
| pio1 | sm1 | ring 2, GP3 (GRB order) |

The rings share a single program load in pio1; the status LED owns pio0 so the
bootloader (which links only the status LED) and the app never contend.

### Concurrency
Single-core cooperative super-loop on core0 at **~500 Hz** (2 ms tick): each pass
services the status LED, detects TCP peer connect edges (→ `hello`), samples and
debounces the buttons, accumulates inbound bytes into lines and dispatches complete
commands, and flushes dirty ring frames (the 2 ms gap between passes satisfies the
WS2812 >50 µs inter-frame latch). Deterministic and simple.

**Line framing is a deliberate upgrade over the keypad firmware**, which only
`strstr()`-scanned the inbound stream for the OTA trigger: the panel buffers bytes into
`\n`-terminated lines, parses each through `protocol.c`, and dispatches on the command
type — so every command (`ring`, `lamp`, `config`, `ping`, `ota`) gets real parsing,
acks, and error replies. Overlong lines are dropped with an `err` and the parser
resyncs at the next newline; a half-line left over from a previous connection is
discarded on peer reconnect.

## Wire protocol (line-delimited JSON over TCP, port 5005)

### Device → host (events)
```json
{"t":"hello","fw":"1.0.0","buttons":2,"rings":[16,16],"pressed":[false,false],"ip":"10.74.29.13"}
{"t":"btn","id":1,"e":"down","ms":123456}
{"t":"btn","id":1,"e":"up","ms":124102}
{"t":"ack","cmd":"ring"}
{"t":"err","msg":"bad ring cmd"}
```
The `hello` is sent on **every TCP peer connect** (TCPS pin edge) — firmware version,
ring sizes, and current debounced button states — so the host can resync after either
side restarts. This is the hook the ROS driver uses to re-push desired state.

**Do not rely on the unsolicited hello alone:** some CH9120 batches never assert the
TCPS pin (observed on a 2026 unit — the pin is actively driven but stays HIGH with a
live TCP connection), so the connect edge never fires. Hosts should send
`{"cmd":"hello"}` right after connecting (fw ≥ 1.0.3 replies with the hello line); on
units where TCPS does work, the duplicate hello is a harmless double resync.

### Host → device (commands)
```json
{"cmd":"ring","id":1,"r":255,"g":64,"b":0,"brightness":128}
{"cmd":"lamp","on":true}
{"cmd":"config","debounce_ms":30}
{"cmd":"ping"}
{"cmd":"hello"}
{"cmd":"ota"}
```
- `ring`: `id` 1–2; `r/g/b` 0–255; `brightness` 0–255. **Absent fields keep their
  current value** (e.g. brightness-only fades, color-only changes). The whole ring is
  one uniform color.
- `lamp`: button 1's illumination, on/off.
- `config`: `debounce_ms` 1–1000, applies immediately (not persisted).
- `hello`: request the hello line; the reply is the hello event itself, not an ack.
- `ota`: ack, then reboot into bootloader recovery ([`OTA.md`](OTA.md)).
- Unknown/invalid commands → `{"t":"err",...}`; valid → `{"t":"ack",...}`.

## No flash persistence (deliberate)

Ring colors, brightness, lamp state, and the debounce override are **not persisted to
flash** — a deliberate deviation from our usual persist-user-settings rule for embedded
UIs. Rationale:

- The panel is a **host-commanded peripheral**, not a self-contained UI. The ROS 2
  driver is the single source of truth for desired state and **re-sends it on every
  reconnect** — the device emits `hello` on every TCP connect precisely to trigger
  that resync. Persisted device-side state would be stale the moment the driver
  reconnects, so it buys nothing.
- Ring commands can arrive at animation rates; writing each one to flash would **wear
  the sector for no benefit** (and stall the super-loop during erase).
- A defined dark power-on state is the safer default for an operator panel: a stale
  persisted "GO" green ring after a power cycle would be a false indication.

**Power-on state:** rings dark (brightness scale full, so the first color command shows
correctly), lamp off — until the host connects and commands otherwise.

## WS2812 byte order (gotcha) + self-test

The **onboard GP25 LED latches RGB** — a board anomaly verified by self-test in the
keypad project (`status_led.c` sends RGB). External ring modules are **standard GRB**;
`RING_COLOR_ORDER_GRB` in `config.h` defaults to 1. Don't "fix" one by breaking the
other — the orders are per-chain and `rings.c` packs them independently of the status
LED.

To verify a new ring batch:
```bash
cmake -B build -DRING_SELFTEST=1 && cmake --build build -j
```
The self-test build skips networking and cycles pure logical **RED 1 s / GREEN 2 s /
BLUE 4 s** on both rings — watch the **dwell time** to identify which channel is
actually lit (a GRB ring driven as RGB shows green during the 1 s "RED" phase). It also
echoes raw button edges on USB serial and drives the lamp from button 1, so the full
panel is bench-testable with no network.

## Configuration
Compile-time defaults in `src/config.h`: pins, ring LED counts (`RING1_NUM_LEDS` /
`RING2_NUM_LEDS`, both 16), color order, debounce 30 ms, IP mode `NET_USE_DHCP` +
static IP/mask/gw for the static option, TCP port 5005. The only runtime override is
`debounce_ms` via the `config` command (intentionally not persisted — see above).

## Testing
`pytest` drives the pure modules through `ctypes` against a host-compiled shared lib
(`tools/test.sh`):
- buttons — debounce stable-time gating, first-sample seeding (no boot edge), edge timing.
- rings — keep-current semantics of absent fields, brightness scaling rounding,
  GRB/RGB packing, dirty-flag behavior.
- protocol — round-trip command parse + event format, malformed input, absent fields → -1.

Hardware glue (GPIO, PIO, CH9120) is verified on-target (`RING_SELFTEST`,
[`BRINGUP.md`](BRINGUP.md)), not unit tested. The OTA path additionally has a host-side
failure-injection suite (a faithful device+CH9120-bridge simulator driven by the real
flasher) — see [`OTA.md`](OTA.md) and `tools/test_ota.sh`.

## Open / deferred
- Per-LED ring patterns (spinner/progress) — current protocol is one uniform color per
  ring; per-LED frames would need a bulk command and a faster dirty path.
- TLS / auth on the socket (currently trusted LAN assumption).
- Brightness-limited "panel test" command (all-white at capped brightness) for field
  diagnostics within the power budget.
