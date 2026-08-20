/*
 * rings_hw.c — GLUE: PIO for the WS2812 rings (see rings_hw.h).
 */
#include "rings/rings_hw.h"
#include "rings/rings.h"
#include "config.h"

#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "ws2812.pio.h"

#define RINGS_PIO pio1 /* status_led owns pio0 */

static const uint s_pins[RING_COUNT] = { RING1_PIN, RING2_PIN };

void rings_hw_init(void) {
    uint offset = pio_add_program(RINGS_PIO, &ws2812_program);
    for (uint sm = 0; sm < RING_COUNT; sm++) {
        ws2812_program_init(RINGS_PIO, sm, offset, s_pins[sm], 800000, false);
    }
}

void rings_hw_push(int idx, const uint32_t *words, int count) {
    if (idx < 0 || idx >= RING_COUNT) return;
    /* Ensure the WS2812 reset/latch gap (>=280us) since the previous frame on this
     * chain, so a frame pushed shortly after another (e.g. the boot all-off flush
     * immediately followed by the first commanded/self-test color) latches instead
     * of fusing. Rings are command-driven, so this brief wait is not on a hot path. */
    sleep_us(300);
    for (int i = 0; i < count; i++) {
        /* 24-bit pixel in the top bits, as the PIO's left-shift autopull expects. */
        pio_sm_put_blocking(RINGS_PIO, (uint)idx, words[i] << 8u);
    }
}
