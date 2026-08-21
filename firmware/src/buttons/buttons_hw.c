/*
 * buttons_hw.c — GLUE: GPIO for buttons + lamp (see buttons_hw.h).
 */
#include "buttons/buttons_hw.h"
#include "config.h"

#include "pico/stdlib.h"

static const uint s_btn_pins[BTN_COUNT] = { BUTTON1_PIN, BUTTON2_PIN };
static bool s_lamp_on = false;

void buttons_hw_init(void) {
    for (int i = 0; i < BTN_COUNT; i++) {
        gpio_init(s_btn_pins[i]);
        gpio_set_dir(s_btn_pins[i], GPIO_IN);
        gpio_pull_up(s_btn_pins[i]); /* button shorts the pin to GND when pressed */
    }
    gpio_init(LAMP_PIN);
    gpio_set_dir(LAMP_PIN, GPIO_OUT);
    gpio_put(LAMP_PIN, 0);
}

void buttons_hw_read(bool raw[BTN_COUNT]) {
    for (int i = 0; i < BTN_COUNT; i++) {
        raw[i] = !gpio_get(s_btn_pins[i]); /* active-low */
    }
}

void lamp_hw_set(bool on) {
    s_lamp_on = on;
    gpio_put(LAMP_PIN, on);
}

bool lamp_hw_get(void) {
    return s_lamp_on;
}
