/*
 * ota_app.h — application-side OTA hooks.
 *
 * ota_confirm(): once the app has booted and proven healthy (network up), mark the
 *   image confirmed so the bootloader stops counting boot attempts / won't revert.
 * ota_request_update(): signal the bootloader (watchdog scratch) and reboot into
 *   network recovery to receive a new image.
 */
#ifndef KEYPAD_OTA_APP_H
#define KEYPAD_OTA_APP_H

void ota_confirm(void);
void ota_request_update(void) __attribute__((noreturn));

#endif /* KEYPAD_OTA_APP_H */
