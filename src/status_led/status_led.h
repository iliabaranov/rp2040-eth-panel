/*
 * status_led.h — onboard WS2812 RGB LED (GP25) used as a headless status display.
 *
 * Flashes the last octet of the IP address digit-by-digit so the device's address
 * can be read off the LED with no serial console: each decimal digit is shown as
 * that many short pulses (a 0 is one long pulse), with a gap between digits and a
 * longer gap before the sequence repeats. The on-colour distinguishes DHCP (green)
 * from a static-fallback address (amber). Non-blocking: call status_led_task()
 * frequently from the main loop.
 */
#ifndef PANEL_STATUS_LED_H
#define PANEL_STATUS_LED_H

#include <stdint.h>

void status_led_init(void);

/* Set the on-colour of the pulses (0..255 each). */
void status_led_set_color(uint8_t r, uint8_t g, uint8_t b);

/* Begin flashing this value (the IP's last octet, 0..255), repeating. */
void status_led_show_octet(uint8_t octet);

/* Advance the blink state machine; non-blocking. Call often. */
void status_led_task(void);

/* Light the LED a solid colour immediately (bypasses the blink machine).
 * Channel args are logical r,g,b; used by the color self-test. */
void status_led_solid(uint8_t r, uint8_t g, uint8_t b);

#endif /* PANEL_STATUS_LED_H */
