/*
 * crc32.h — standard reflected CRC-32 (poly 0xEDB88320), matching Python zlib.crc32
 * and the host OTA flasher. Pure, host-buildable.
 */
#ifndef KEYPAD_OTA_CRC32_H
#define KEYPAD_OTA_CRC32_H

#include <stddef.h>
#include <stdint.h>

/* One-shot CRC-32 over a buffer (== zlib.crc32(data)). */
uint32_t ota_crc32(const uint8_t *data, size_t len);

#endif /* KEYPAD_OTA_CRC32_H */
