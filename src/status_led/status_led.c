/*
 * status_led.c — WS2812 IP-octet flasher (see status_led.h).
 */
#include "status_led/status_led.h"
#include "config.h"

#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "ws2812.pio.h"

/* Blink timing (ms) */
#define PULSE_ON_MS   180
#define PULSE_OFF_MS  220
#define ZERO_ON_MS    600   /* a 0 digit = one long pulse */
#define DIGIT_GAP_MS  700
#define REPEAT_GAP_MS 2200

#define WS2812_PIN     STATUS_LED_PIN
#define WS2812_IS_RGBW false

typedef enum { ST_PULSE_ON, ST_PULSE_OFF, ST_DIGIT_GAP, ST_REPEAT_GAP } phase_t;

static PIO     s_pio = pio0;
static uint    s_sm  = 0;
static uint8_t s_r = 0, s_g = 40, s_b = 0; /* dim green default */

static uint8_t s_digits[3];
static int     s_ndigits = 1;
static int     s_di;            /* current digit index */
static int     s_pulses_done;
static int     s_pulses_target;
static bool    s_zero_digit;
static phase_t s_phase;
static absolute_time_t s_next;

/* This board's WS2812B latches bytes in RGB order (verified by self-test: with
 * GRB packing, "green" showed red). Send red, then green, then blue. */
static void put_color(uint8_t r, uint8_t g, uint8_t b) {
    uint32_t rgb = ((uint32_t)r << 16) | ((uint32_t)g << 8) | b;
    pio_sm_put_blocking(s_pio, s_sm, rgb << 8u);
}
static void led_on(void)  { put_color(s_r, s_g, s_b); }
static void led_off(void) { put_color(0, 0, 0); }

static void begin_digit(int i) {
    s_zero_digit    = (s_digits[i] == 0);
    s_pulses_target = s_zero_digit ? 1 : s_digits[i];
    s_pulses_done   = 0;
    led_on();
    s_phase = ST_PULSE_ON;
    s_next  = make_timeout_time_ms(s_zero_digit ? ZERO_ON_MS : PULSE_ON_MS);
}

void status_led_init(void) {
    uint offset = pio_add_program(s_pio, &ws2812_program);
    ws2812_program_init(s_pio, s_sm, offset, WS2812_PIN, 800000, WS2812_IS_RGBW);
    led_off();
}

void status_led_set_color(uint8_t r, uint8_t g, uint8_t b) {
    s_r = r; s_g = g; s_b = b;
}

void status_led_solid(uint8_t r, uint8_t g, uint8_t b) {
    put_color(r, g, b);
}

void status_led_show_octet(uint8_t octet) {
    /* Decimal digits, no leading zeros. */
    if (octet >= 100) {
        s_digits[0] = octet / 100;
        s_digits[1] = (octet / 10) % 10;
        s_digits[2] = octet % 10;
        s_ndigits = 3;
    } else if (octet >= 10) {
        s_digits[0] = octet / 10;
        s_digits[1] = octet % 10;
        s_ndigits = 2;
    } else {
        s_digits[0] = octet;
        s_ndigits = 1;
    }
    s_di = 0;
    begin_digit(0);
}

void status_led_task(void) {
    if (!time_reached(s_next)) return;

    switch (s_phase) {
    case ST_PULSE_ON:
        led_off();
        s_pulses_done++;
        if (s_pulses_done >= s_pulses_target) {
            s_phase = ST_DIGIT_GAP;
            s_next  = make_timeout_time_ms(DIGIT_GAP_MS);
        } else {
            s_phase = ST_PULSE_OFF;
            s_next  = make_timeout_time_ms(PULSE_OFF_MS);
        }
        break;

    case ST_PULSE_OFF:
        led_on();
        s_phase = ST_PULSE_ON;
        s_next  = make_timeout_time_ms(PULSE_ON_MS);
        break;

    case ST_DIGIT_GAP:
        s_di++;
        if (s_di >= s_ndigits) {
            s_phase = ST_REPEAT_GAP;
            s_next  = make_timeout_time_ms(REPEAT_GAP_MS);
        } else {
            begin_digit(s_di);
        }
        break;

    case ST_REPEAT_GAP:
        s_di = 0;
        begin_digit(0);
        break;
    }
}
