# Changelog

## v1.0.3 — 2026-08-19 (first public release)

### Firmware
- **New `{"cmd":"hello"}` request verb** — the device replies with the hello
  line (fw version, ring sizes, current button states). Motivation: some
  CH9120 batches never assert the TCPS status pin, so the unsolicited
  connect-time hello never fires on those units and hosts got no state
  resync. Diagnosed on real hardware: the pin is actively driven HIGH by the
  CH9120 even with a live TCP connection (not a solder/trace fault).

### ROS 2 driver
- **Hello request as a delayed fallback** — the driver waits ~1 s for the
  device's connect-time hello and requests one only if it hasn't arrived.
  Sent in the same instant as the connect, the request races the device's
  connect-edge RX flush on TCPS-working units and arrives truncated (the
  device errs `no cmd` on every connect).
- **RX-fed liveness keepalive** — the CH9120 serves one TCP client and
  silently drops a displaced one (no FIN/RST), stranding a naive client on a
  half-open socket: `recv()` times out quietly forever while sends vanish
  into the local TCP buffer, so the driver looked connected while the device
  had stopped listening. The driver now pings after 2 s of receive-silence
  and declares the connection dead after 6 s without receiving anything,
  then reconnects and resyncs desired state automatically (~8 s worst-case
  outage, no manual restart). Liveness counts received traffic only —
  successful sends prove nothing on a half-open socket. Bonus observed on
  hardware: the keepalive traffic also prevents displacement — the CH9120
  keeps the data path on the actively-talking client; only idle clients lose
  it. New parameters: `keepalive_period` (2.0 s), `liveness_timeout` (6.0 s).
- The standalone example requests the hello after a short grace period; the
  mock panel server answers `hello` and `ping` like the real firmware.

### CAD
- One-button panel variant: new top casing (single top button, front
  illuminated button omitted), lid with stabilizer. The firmware needs no
  change for this variant — button 1 reads not-pressed and the lamp output
  is left unconnected.

### Protocol notes for host implementers
- Do not rely on the unsolicited connect-time hello; request one if none
  arrives shortly after connecting.
- Never send in the same instant as the connect — the device's connect-edge
  RX flush can truncate a line already in flight.
- Treat received traffic as the only liveness evidence and reconnect after
  an RX-silence timeout.

## v1.0.2 — 2026-06-12
- Verified the OTA-only update path (Ethernet, no USB attached).
- Standalone example fix: clear the socket timeout inherited from
  `create_connection` so the reader thread survives idle periods.
- Documentation accuracy fixes; hardware bring-up record in
  `docs/BRINGUP.md`.

## v1.0.1 — 2026-06-11
- 25 confirmed fixes from an adversarial review, including: UART RX IRQ ring
  buffer (32-byte FIFO overrun at 115200 baud), WS2812 inter-frame latch
  gap, button state/event desync, button-held-at-boot seeding before hello,
  overlong-line discard state, driver socket teardown and thread join on
  shutdown, send-failure resync.

## v1.0.0 — 2026-06-11
- Initial release: immutable bootloader with OTA recovery (app at
  0x10040000, CRC-verified updates over Ethernet), panel application
  (2 buttons, 2×16-LED WS2812 rings, button lamp), CH9120 TCP:5005
  line-delimited JSON protocol, ROS 2 Humble driver package, standalone
  example, mock device server, host-side test suite, USB provisioning and
  OTA tools.
