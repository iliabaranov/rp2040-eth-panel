/*
 * boot_state.h — persistent, power-fail-safe boot-state (two ping-pong sectors).
 *
 * Used by the bootloader (read decision; write app_valid/attempts) and the app
 * (set app_confirmed). Uses the Pico flash API, so firmware-only.
 */
#ifndef KEYPAD_OTA_BOOT_STATE_H
#define KEYPAD_OTA_BOOT_STATE_H

#include <stdbool.h>
#include "ota/layout.h"

/* Read the newest valid record into *out. Returns false if neither sector holds
 * a valid (magic + CRC) record. */
bool boot_state_read(boot_state_t *out);

/* Persist *in: fills magic/seq/crc and writes to the older sector so the current
 * newest record survives an interrupted write. */
void boot_state_write(boot_state_t *in);

#endif /* KEYPAD_OTA_BOOT_STATE_H */
