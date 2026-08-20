/*
 * recovery.c — bootloader network recovery: receive a new app image over the
 * CH9120 TCP socket and flash it into the app slot. See docs/OTA.md for the
 * protocol. Lock-step (per-chunk ACK) so the host pauses during flash ops.
 */
#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"
#include "hardware/structs/xip_ctrl.h"

#include "config.h"
#include "ota/layout.h"
#include "ota/crc32.h"
#include "ota/boot_state.h"
#include "net/net.h"
#include "status_led/status_led.h"

/* recovery LED colors (logical r,g,b; board is RGB-order, handled in status_led) */
#define LED_RECOVERY 60, 0, 60   /* purple: waiting/active */
#define LED_DONE     0, 60, 0    /* green: image accepted */
#define LED_ERROR    60, 0, 0    /* red: CRC/size error */

static uint8_t s_chunk[OTA_CHUNK_SIZE];

/* Known 4-byte command magics. The recovery loop resyncs to one of these at every
 * command boundary (see read_command), so stray/duplicate bytes can't shift framing. */
static const char *const CMD_MAGICS[] = { "RP2B", "BEGN", "DATA", "END!", "GO!!" };
#define N_CMD_MAGICS ((int)(sizeof(CMD_MAGICS) / sizeof(CMD_MAGICS[0])))

/* Read exactly n bytes; timeout resets on any progress. */
static bool read_exact(uint8_t *buf, int n, uint32_t timeout_ms) {
    int got = 0;
    absolute_time_t dl = make_timeout_time_ms(timeout_ms);
    while (got < n) {
        int r = net_read(buf + got, n - got);
        if (r > 0) {
            got += r;
            dl = make_timeout_time_ms(timeout_ms);
        } else if (time_reached(dl)) {
            return false;
        } else {
            tight_loop_contents();
        }
    }
    return true;
}

/* Read the next command, resynchronizing to a known 4-byte magic. Bytes are taken
 * one at a time into a sliding window; junk (stale bytes left in the CH9120 from a
 * dropped/retried connection, a late duplicate SYNC, a partial frame) is skipped
 * until a real command boundary is found. This makes the receiver immune to framing
 * drift: a single lost/extra byte can no longer desync the entire session.
 * Returns false only after `timeout_ms` with no bytes at all (used for idle LED
 * re-assert). The matched 4 bytes are returned in `out`. */
static bool read_command(uint8_t out[4], uint32_t timeout_ms) {
    uint8_t w[4] = { 0, 0, 0, 0 };
    int filled = 0;
    absolute_time_t dl = make_timeout_time_ms(timeout_ms);
    for (;;) {
        uint8_t b;
        if (net_read(&b, 1) == 1) {
            w[0] = w[1]; w[1] = w[2]; w[2] = w[3]; w[3] = b;
            if (filled < 4) filled++;
            if (filled == 4) {
                for (int i = 0; i < N_CMD_MAGICS; i++) {
                    if (!memcmp(w, CMD_MAGICS[i], 4)) {
                        memcpy(out, w, 4);
                        return true;
                    }
                }
            }
            dl = make_timeout_time_ms(timeout_ms);  /* progress: extend */
        } else if (time_reached(dl)) {
            return false;
        } else {
            tight_loop_contents();
        }
    }
}

static bool read_u32(uint32_t *v, uint32_t timeout_ms) {
    uint8_t b[4];
    if (!read_exact(b, 4, timeout_ms)) return false;
    *v = (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
    return true;
}

static void write_tok(const char *tok) { net_write((const uint8_t *)tok, 4); }
static void write_u32(uint32_t v) {
    uint8_t b[4] = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
    net_write(b, 4);
}

static void erase_slot(uint32_t len) {
    uint32_t nsec = (len + FLASH_SECTOR - 1) / FLASH_SECTOR;
    for (uint32_t i = 0; i < nsec; i++) {
        uint32_t ints = save_and_disable_interrupts();
        flash_range_erase(APP_OFFSET + i * FLASH_SECTOR, FLASH_SECTOR);
        restore_interrupts(ints);
    }
}

static void program_chunk(uint32_t off, uint8_t *buf, uint32_t len) {
    uint32_t plen = (len + (FLASH_PAGE_SIZE - 1)) & ~(FLASH_PAGE_SIZE - 1);
    for (uint32_t i = len; i < plen; i++) buf[i] = 0xFF;  /* pad page tail */
    uint32_t ints = save_and_disable_interrupts();
    flash_range_program(APP_OFFSET + off, buf, plen);
    restore_interrupts(ints);
}

void recovery_run(void) {
    status_led_init();
    status_led_solid(LED_RECOVERY);

    /* Attach to the CH9120's EXISTING config (it persists across the RP2040
     * reboot) instead of reconfiguring — fast, and keeps the same IP so the host
     * reconnects to the address it already knew. */
    net_attach_data_mode();
    printf("[recovery] OTA server ready on tcp :%u\n", NET_LOCAL_PORT);
    status_led_solid(LED_RECOVERY);

    uint32_t app_len = 0, app_crc = 0;
    uint8_t tok[4];

    for (;;) {
        if (!read_command(tok, 1000)) {
            status_led_solid(LED_RECOVERY);  /* idle re-assert */
            continue;
        }

        if (!memcmp(tok, "RP2B", 4)) {              /* SYNC: "RP2BOOT1" */
            uint8_t rest[4];
            read_exact(rest, 4, 1000);              /* "OOT1" */
            write_tok("BLOK");
            write_u32(APP_MAX_SIZE);
            write_u32(OTA_CHUNK_SIZE);
            printf("[recovery] SYNC\n");
        } else if (!memcmp(tok, "BEGN", 4)) {       /* BEGIN: len, crc */
            if (!read_u32(&app_len, 2000) || !read_u32(&app_crc, 2000)) continue;
            if (app_len == 0 || app_len > APP_MAX_SIZE) { write_tok("ERSZ"); continue; }
            printf("[recovery] BEGIN len=%lu crc=%08lx — erasing\n",
                   (unsigned long)app_len, (unsigned long)app_crc);
            erase_slot(app_len);
            write_tok("OKER");
        } else if (!memcmp(tok, "DATA", 4)) {       /* DATA: off,len,crc,payload */
            uint32_t off, len, ccrc;
            if (!read_u32(&off, 2000) || !read_u32(&len, 2000) || !read_u32(&ccrc, 2000)) continue;
            if (len == 0 || len > OTA_CHUNK_SIZE || off + len > APP_MAX_SIZE) {
                write_tok("DNAK"); write_u32(off); continue;
            }
            if (!read_exact(s_chunk, (int)len, 5000)) { write_tok("DNAK"); write_u32(off); continue; }
            if (ota_crc32(s_chunk, len) != ccrc)      { write_tok("DNAK"); write_u32(off); continue; }
            program_chunk(off, s_chunk, len);
            write_tok("DACK"); write_u32(off);
        } else if (!memcmp(tok, "END!", 4)) {       /* END: verify whole-slot CRC */
            /* Flush the XIP cache so the cached read sees freshly-programmed flash.
             * (Reading the non-cached alias instead leaves XIP in a streaming mode
             * that stalls the following flash_range_erase in boot_state_write.) */
            xip_ctrl_hw->flush = 1;
            (void)xip_ctrl_hw->flush;  /* read-back blocks until the flush completes */
            uint32_t crc = ota_crc32((const uint8_t *)APP_XIP_ADDR, app_len);
            printf("[recovery] END verify: crc=%08lx want=%08lx\n",
                   (unsigned long)crc, (unsigned long)app_crc);
            if (crc == app_crc) {
                boot_state_t st;
                memset(&st, 0, sizeof st);
                st.app_len = app_len;
                st.app_crc32 = app_crc;
                st.app_valid = 1;
                boot_state_write(&st);
                printf("[recovery] boot_state written\n");
                write_tok("DONE");
                status_led_solid(LED_DONE);
                printf("[recovery] image verified -> DONE\n");
            } else {
                write_tok("ECRC");
                status_led_solid(LED_ERROR);
                printf("[recovery] CRC mismatch -> ECRC\n");
            }
        } else if (!memcmp(tok, "GO!!", 4)) {       /* reboot into the new app */
            write_tok("BYE!");
            printf("[recovery] rebooting\n");
            sleep_ms(150);
            watchdog_reboot(0, 0, 0);
        }
    }
}
