/*
 * apptest/main.c — minimal offset-slot app for isolating the bootloader jump.
 *
 * Links at 0x10040000 (same as the real app) but does almost nothing: alternates
 * the WS2812 green/blue and prints a USB-serial heartbeat. Provision the
 * bootloader + this, and:
 *   - LED alternating green/blue  => the jump works and the app runs.
 *   - USB heartbeat readable      => USB survives the hand-off.
 *   - LED dark                    => hung in crt0/jump (before main).
 * This separates the jump itself from net_init()/CH9120, which is where the full
 * app may be hanging.
 */
#include <stdio.h>

#include "pico/stdlib.h"
#include "status_led/status_led.h"

int main(void) {
    stdio_init_all();
    status_led_init();

    uint32_t i = 0;
    bool on = false;
    while (true) {
        if (on) status_led_solid(0, 60, 0);   /* green */
        else    status_led_solid(0, 0, 60);    /* blue  */
        printf("[apptest] alive %lu (jump + USB OK)\n", (unsigned long)i++);
        on = !on;
        sleep_ms(400);
    }
}
