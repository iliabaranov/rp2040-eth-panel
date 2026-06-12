# Over-Ethernet firmware update (OTA)

Robust field updates for the RP2040 over the CH9120 Ethernet bridge, with the
guarantee that **a failed update can never make the device impossible to re-flash
over Ethernet.** This is the same two-stage OTA stack as the sibling
`rp2040-eth-keypad` project (same board, same transport), carried over intact.

## Guarantee & how it holds
The bootloader is the **trust anchor**: it brings up Ethernet and can receive a new
image entirely on its own, and it is **never overwritten by an update**. Therefore,
no matter how an app update fails, the device still boots the bootloader, which still
talks Ethernet and still accepts a fresh image.

- Decisions (chosen 2026): **single app slot + network recovery**, **CRC32 integrity**,
  **immutable bootloader (provisioned once over USB)**.
- Ultimate fallback: the RP2040 mask-ROM **USB BOOTSEL** is always available (physical),
  but the design aims to never need it — Ethernet recovery is the normal safety net.

## Flash map (4 MB W25Q32, XIP base 0x10000000)
| Region | XIP address | Flash offset | Size | Notes |
|--------|-------------|--------------|------|-------|
| Bootloader | 0x10000000 | 0x000000 | 256 KB | immutable; own boot2, CH9120, recovery, flash writer |
| App slot | 0x10040000 | 0x040000 | 0x3BE000 (~3.74 MB) | single application image |
| Boot-state A | 0x103FE000 | 0x3FE000 | 4 KB | redundant, CRC'd |
| Boot-state B | 0x103FF000 | 0x3FF000 | 4 KB | redundant, CRC'd |

App images are ~100–200 KB, so the slot is far larger than needed (room to grow).
Definitions shared by bootloader and app live in `src/ota/layout.h`.

## Images & jump
- Both bootloader and app are normal Pico-SDK binaries (each has its own boot2). The
  **bootrom** only runs the bootloader's boot2 at 0x10000000.
- The app is **linked at 0x10040000**. The bootloader (XIP already configured) hands
  off by: validating the app, `__disable_irq()`, deinit of peripherals it used, set
  `VTOR = 0x10040100` (app vector table, after the app's unused boot2), load MSP from
  `[0x10040100]`, jump to reset vector `[0x10040104]`.

## Boot-state (power-fail-safe)
Two 4 KB sectors written ping-pong (write the newer record to the older sector) so an
interrupted write always leaves the previous valid record intact.
```
struct boot_state {
  uint32_t magic;        // 'B''S''T''1'
  uint32_t seq;          // monotonically increasing; higher = newer
  uint32_t app_len;      // bytes of the app image
  uint32_t app_crc32;    // CRC32 over [APP_BASE .. APP_BASE+app_len)
  uint8_t  app_valid;    // image fully received + CRC-verified at flash time
  uint8_t  app_confirmed;// app proved healthy (network up) post-update
  uint8_t  boot_attempts;// boots since flashed without a confirm
  uint8_t  _pad;
  uint32_t crc32;        // CRC32 over the struct above
};
```
The CRC32 is the standard zlib polynomial — `zlib.crc32()` on the host computes
bit-identical values, which is what `tools/ota_flash.py` uses.

## Boot decision (bootloader)
1. If watchdog `SCRATCH0 == ENTER_UPDATE_MAGIC` (`0x0B00B1E5`) → **recovery** (app
   explicitly requested it).
2. Else if `!app_valid` or slot CRC re-check fails → **recovery** (no good image).
3. Else if `app_confirmed` → **boot app** (reset boot_attempts).
4. Else (valid but unconfirmed — a freshly flashed image): if `boot_attempts >= 3` →
   mark `app_valid=0` → **recovery**; otherwise `boot_attempts++`, persist, **boot app**.

The app, once it has booted and brought the network up successfully, calls
`ota_confirm()` which sets `app_confirmed=1`, `boot_attempts=0`. So a CRC-valid image
that crashes or can't network is auto-dropped to recovery after 3 boots.

## Recovery / update protocol (binary, little-endian, over the CH9120 TCP socket)
The CH9120 bridges TCP↔UART, so this runs over the same socket the app uses. Each
message starts with a 4-byte magic; all integers are little-endian u32. Lock-step:
each DATA waits for its ACK so the sender pauses during flash erase/program (no UART
overrun). Both ends resync to these magics (see *Transport robustness* below).

| Step  | Host → device                              | Device → host                          |
|-------|--------------------------------------------|----------------------------------------|
| SYNC  | `"RP2BOOT1"` (8 bytes)                      | `"BLOK"` + `slot_size` + `max_chunk` (or no reply if it's the app) |
| BEGIN | `"BEGN"` + `app_len` + `app_crc32`          | `"OKER"` after erasing the slot (`"ERSZ"` if size is bad) |
| DATA  | `"DATA"` + `off` + `len` + `chunk_crc32` + payload | `"DACK"` + `off` (or `"DNAK"` + `off` to resend) |
| END   | `"END!"`                                    | flush XIP, verify whole-slot CRC == `app_crc32`, write boot-state → `"DONE"` (or `"ECRC"`) |
| GO    | `"GO!!"`                                     | `"BYE!"`, then reboot into the app     |

Entering update mode from the running app: the app receives `{"cmd":"ota"}` on its
normal JSON socket — parsed as a first-class command by the protocol module
(`proto_parse` → `CMD_OTA`, like any other command; the keypad's app merely
`strstr()`-scanned the stream for it) → acks `{"t":"ack","cmd":"ota"}` → writes
`SCRATCH0 = ENTER_UPDATE_MAGIC` → `watchdog_reboot()`. The host flasher waits for that
ack and then reconnects to the same IP and runs SYNC (re-triggering if the ack was
lost — see *Transport robustness*).

## Failure handling (why each case stays recoverable)
- **Dropped/garbled transfer or bad chunk CRC** → image never CRC-verifies → `app_valid`
  stays 0 → bootloader remains in recovery → re-push.
- **Power loss mid-erase/program** → slot partially written, `app_valid` not set (or slot
  CRC re-check fails) → recovery on next boot.
- **Power loss mid boot-state write** → ping-pong leaves the prior record valid.
- **Valid CRC but the new app crashes / can't network** → never confirmed → after 3 boots
  bootloader drops to recovery.
- **Bootloader corruption** → not written during OTA (immutable); USB BOOTSEL recovers.

## Implementation notes (verified end-to-end over Ethernet on this board family)
- **Flash size:** the boot-state sectors live near the top of the 4 MB chip
  (`0x3FE000`), so the build MUST set `PICO_FLASH_SIZE_BYTES=4194304` — otherwise the
  Pico SDK's `flash_range_erase`/`program` `hard_assert(offs <= PICO_FLASH_SIZE_BYTES)`
  (default 2 MB) panics. (Set in the top-level `CMakeLists.txt`.)
- **App hand-off:** `jump_to_app` disables NVIC IRQs + SysTick but must **not** set
  PRIMASK (`cpsid i`) — the app's early init (`sleep_ms`/stdio) relies on the timer-alarm
  IRQ, so global interrupts must stay enabled.
- **Recovery is fast:** recovery does *not* reconfigure the CH9120; it light-attaches to
  the chip's existing config (`net_attach_data_mode()` — UART at the data baud, CFG high).
  The CH9120 keeps its config + DHCP lease across an RP2040-only reboot, so recovery comes
  up in <1 s and the host reconnects to the same IP.
- **Whole-image CRC at END:** flush the XIP cache, then read via the normal cached alias.
  (Reading the non-cached alias left XIP in a streaming mode that stalled the subsequent
  `flash_range_erase`.)
- **Host flasher:** sends the `{"cmd":"ota"}` trigger on the *same* socket as the SYNC
  probe — the CH9120 is a single-client TCP server and a second socket to a running app
  wedges it.

## Transport robustness (CH9120 is a frameless byte stream)
The CH9120 is a transparent TCP↔UART bridge with **no message framing** and a
single-client server that buffers across connections. Two field-failure classes came
from this, both now defended on *both* ends:

- **Framing desync from stray/stale bytes.** A dropped or retried connection (e.g. the
  host's `ensure_recovery` probing SYNC) can leave bytes buffered in the bridge that
  arrive on the *next* connection, or a late duplicate response can precede the one
  expected. If either end consumed a fixed 4 bytes as "the next token", a single
  misaligned byte shifted *all* subsequent frames — so the push timed out at a
  *random* phase (this is exactly why the observed failure point moved between BEGIN
  and END across runs). **Fix:** both ends **resync to a known token** by sliding a
  4-byte window one byte at a time until a valid command/response magic appears
  (device: `read_command` in `recovery.c`; host: `read_token` in `ota_flash.py`), and
  the host **drains** stale bytes before each phase. Stray bytes are now skipped, not
  fatal.
- **Lost bytes / link blips.** A corrupted chunk fails its CRC → `DNAK` → the host
  **re-sends that chunk** (cheap, local recovery, retried generously). A connection-level
  fault (peer close, token timeout) instead propagates to the host's **whole-flash
  retry**, which restarts from SYNC on a fresh connection — safe because a partially
  written slot never sets `app_valid`, so the bootloader simply stays in recovery.
- **Lost update trigger.** Just after a reboot the app spends ~10 s reconfiguring the
  CH9120 and isn't reading the socket, so a blind one-shot `{"cmd":"ota"}` is easily
  dropped. The host's `ensure_recovery()` therefore treats **SYNC as the source of
  truth**: it re-probes and **re-sends the trigger, waiting for the app's ack**, until
  recovery actually answers. (The old code assumed a failed attempt had already reached
  recovery and skipped re-triggering — which stalled whenever the trigger was lost in
  that window. Sending the trigger to a device already in recovery is harmless: the
  receiver resyncs past the JSON.)

**Hardware-verified** in the sibling keypad project (identical board, bootloader, and
transport): 8 consecutive no-touch OTA cycles over Ethernet (alternating two build
versions), each confirmed end-to-end via the recovery serial trace — `BEGIN` CRC ==
pushed CRC, `END verify` match, `boot_state written`, `DONE`, reboot into the pushed
version, `app confirmed healthy` — with no USB and no human intervention. The panel's
own on-board OTA cycle is step 7 of [`BRINGUP.md`](BRINGUP.md).

**Testing:** `test/test_ota_flash.py` runs the real host flasher against a faithful
device+CH9120 simulator (`test/ota_sim.py`) across **hundreds of pushes** with injected
faults — stale prefixes (incl. duplicate SYNC), mid-transfer connection resets, and
random byte loss — asserting a byte-exact image lands every time the faults are
individually recoverable. This is the regression guard for the desync bug.

## Development / recovery notes
The bootloader brings up USB stdio in the recovery path for diagnostics; the normal boot
path stays USB-free for a clean, fast hand-off. If the board becomes unresponsive, press
**RESET** (RUN button) to reboot into the last valid app; **BOOTSEL** + USB is the
ultimate fallback for (re)provisioning. `tools/ota_flash.py --host <ip> build/panel.bin`
performs the full cycle; `--in-recovery` skips the app trigger when the device is
already in recovery.
