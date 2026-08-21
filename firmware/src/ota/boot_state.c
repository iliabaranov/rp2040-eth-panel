/*
 * boot_state.c — ping-pong boot-state in two flash sectors (see boot_state.h).
 */
#include "ota/boot_state.h"
#include "ota/crc32.h"

#include <stddef.h>
#include <string.h>

#include "hardware/flash.h"
#include "hardware/sync.h"

static const boot_state_t *at(uint32_t off) {
    return (const boot_state_t *)(XIP_BASE_ADDR + off);
}

static bool rec_valid(const boot_state_t *r) {
    if (r->magic != BOOT_STATE_MAGIC) return false;
    return ota_crc32((const uint8_t *)r, offsetof(boot_state_t, crc32)) == r->crc32;
}

bool boot_state_read(boot_state_t *out) {
    const boot_state_t *a = at(BOOTSTATE_A_OFFSET);
    const boot_state_t *b = at(BOOTSTATE_B_OFFSET);
    bool av = rec_valid(a), bv = rec_valid(b);
    if (av && bv) { *out = (a->seq >= b->seq) ? *a : *b; return true; }
    if (av) { *out = *a; return true; }
    if (bv) { *out = *b; return true; }
    return false;
}

void boot_state_write(boot_state_t *in) {
    const boot_state_t *a = at(BOOTSTATE_A_OFFSET);
    const boot_state_t *b = at(BOOTSTATE_B_OFFSET);
    bool av = rec_valid(a), bv = rec_valid(b);

    uint32_t maxseq = 0;
    uint32_t target = BOOTSTATE_A_OFFSET;  /* write the OLDER/invalid sector */
    if (av && bv) {
        bool a_newer = a->seq >= b->seq;
        maxseq = a_newer ? a->seq : b->seq;
        target = a_newer ? BOOTSTATE_B_OFFSET : BOOTSTATE_A_OFFSET;
    } else if (av) {
        maxseq = a->seq; target = BOOTSTATE_B_OFFSET;
    } else if (bv) {
        maxseq = b->seq; target = BOOTSTATE_A_OFFSET;
    }

    in->magic = BOOT_STATE_MAGIC;
    in->seq = maxseq + 1;
    in->crc32 = ota_crc32((const uint8_t *)in, offsetof(boot_state_t, crc32));

    uint8_t page[FLASH_PAGE_SIZE];
    memset(page, 0xFF, sizeof page);
    memcpy(page, in, sizeof *in);

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(target, FLASH_SECTOR);
    flash_range_program(target, page, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}
