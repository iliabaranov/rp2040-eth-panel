/*
 * layout.h — shared flash layout, boot-state, and OTA protocol definitions.
 *
 * Included by both the bootloader and the application so the two agree on the
 * partition map, the boot-state record, and the update protocol. See docs/OTA.md.
 *
 * Flash: 4 MB W25Q32, XIP base 0x10000000. Offsets (for flash_range_* APIs) are
 * relative to the start of flash; XIP addresses are offset + 0x10000000.
 */
#ifndef PANEL_OTA_LAYOUT_H
#define PANEL_OTA_LAYOUT_H

#include <stdint.h>

#define XIP_BASE_ADDR 0x10000000u
#define FLASH_TOTAL   (4u * 1024u * 1024u)
#define FLASH_SECTOR  4096u

/* ---- partitions (flash offsets) ---- */
#define BOOTLOADER_OFFSET 0x000000u
#define BOOTLOADER_SIZE   0x040000u            /* 256 KB, immutable */

#define APP_OFFSET        0x040000u            /* app linked at this XIP address */
#define APP_XIP_ADDR      (XIP_BASE_ADDR + APP_OFFSET)
#define APP_VTABLE_ADDR   (APP_XIP_ADDR + 0x100u) /* after the app's (unused) boot2 */

#define BOOTSTATE_A_OFFSET 0x3FE000u
#define BOOTSTATE_B_OFFSET 0x3FF000u

#define APP_MAX_SIZE      (BOOTSTATE_A_OFFSET - APP_OFFSET) /* ~3.74 MB */

/* ---- handshake / limits ---- */
#define OTA_ENTER_UPDATE_MAGIC 0x0B00B1E5u  /* watchdog SCRATCH0 -> recovery */
#define OTA_MAX_BOOT_ATTEMPTS  3            /* unconfirmed boots before recovery */
#define OTA_PROTO_MAGIC        "RP2BOOT1"   /* 8 bytes, SYNC */
#define OTA_CHUNK_SIZE         1024u        /* payload bytes per DATA chunk */

/* ---- boot-state record (one per sector; newest wins by seq) ---- */
#define BOOT_STATE_MAGIC 0x31545342u /* 'B''S''T''1' little-endian */

typedef struct {
    uint32_t magic;
    uint32_t seq;            /* higher = newer */
    uint32_t app_len;        /* bytes of the app image in the slot */
    uint32_t app_crc32;      /* CRC32 over [APP_OFFSET .. +app_len) */
    uint8_t  app_valid;      /* received + CRC-verified at flash time */
    uint8_t  app_confirmed;  /* app proved healthy post-update */
    uint8_t  boot_attempts;  /* boots since flash without a confirm */
    uint8_t  _pad;
    uint32_t crc32;          /* CRC32 over all preceding bytes */
} boot_state_t;

#endif /* PANEL_OTA_LAYOUT_H */
