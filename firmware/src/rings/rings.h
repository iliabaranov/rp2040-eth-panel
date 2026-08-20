/*
 * rings.h — PURE WS2812 ring state: per-ring uniform RGB color + brightness,
 * brightness scaling, and pixel-word packing (no hardware, no SDK calls).
 *
 * The glue (rings_hw) owns the PIO; this module owns what to display. A dirty
 * flag per ring lets the super-loop push frames only when something changed.
 */
#ifndef PANEL_RINGS_H
#define PANEL_RINGS_H

#include <stdbool.h>
#include <stdint.h>

#define RING_COUNT 2

typedef enum {
    RING_ORDER_GRB = 0, /* standard WS2812B modules */
    RING_ORDER_RGB = 1, /* this board's onboard GP25 LED latches RGB */
} ring_order_t;

typedef struct {
    uint8_t r, g, b;    /* commanded color (unscaled) */
    uint8_t brightness; /* 0..255 scale applied to r/g/b on render */
} ring_state_t;

typedef struct {
    ring_state_t st[RING_COUNT];
    uint16_t     nleds[RING_COUNT];
    bool         dirty[RING_COUNT];
} rings_t;

/* Initialize: all rings off (black) at full brightness scale, marked dirty so
 * the first render pushes a known (dark) frame. */
void rings_init(rings_t *rs, const uint16_t nleds[RING_COUNT]);

/* Update ring idx (0-based). Any of r/g/b/brightness may be -1 to keep the
 * current value; values must otherwise be 0..255. Returns false (no change to
 * state) if idx or any present value is out of range. Sets the dirty flag only
 * if the effective state changed. */
bool rings_set(rings_t *rs, int idx, int r, int g, int b, int brightness);

/* Scale one channel by brightness with round-to-nearest (255 = passthrough). */
uint8_t rings_scale(uint8_t c, uint8_t brightness);

/* Pack the ring's scaled color as one 24-bit pixel word (0x00XXYYZZ in wire
 * order, MSB-first as the PIO expects before the <<8 shift). */
uint32_t rings_pixel_word(const rings_t *rs, int idx, ring_order_t order);

/* Fill words[] with nleds copies of the pixel word. Returns the count written,
 * or -1 if idx is invalid / max_words too small. Does NOT clear dirty. */
int rings_render(const rings_t *rs, int idx, ring_order_t order,
                 uint32_t *words, int max_words);

void rings_clear_dirty(rings_t *rs, int idx);

#endif /* PANEL_RINGS_H */
