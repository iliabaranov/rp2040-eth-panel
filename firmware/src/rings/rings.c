/*
 * rings.c — pure WS2812 ring state + packing (see rings.h).
 */
#include "rings/rings.h"

#include <string.h>

void rings_init(rings_t *rs, const uint16_t nleds[RING_COUNT]) {
    memset(rs, 0, sizeof(*rs));
    for (int i = 0; i < RING_COUNT; i++) {
        rs->nleds[i] = nleds[i];
        rs->st[i].brightness = 255;
        rs->dirty[i] = true; /* push an all-off frame on first render */
    }
}

static bool in_range(int v) { return v >= 0 && v <= 255; }

bool rings_set(rings_t *rs, int idx, int r, int g, int b, int brightness) {
    if (idx < 0 || idx >= RING_COUNT) return false;
    if ((r != -1 && !in_range(r)) || (g != -1 && !in_range(g)) ||
        (b != -1 && !in_range(b)) || (brightness != -1 && !in_range(brightness))) {
        return false;
    }
    ring_state_t next = rs->st[idx];
    if (r != -1) next.r = (uint8_t)r;
    if (g != -1) next.g = (uint8_t)g;
    if (b != -1) next.b = (uint8_t)b;
    if (brightness != -1) next.brightness = (uint8_t)brightness;
    if (memcmp(&next, &rs->st[idx], sizeof(next)) != 0) {
        rs->st[idx] = next;
        rs->dirty[idx] = true;
    }
    return true;
}

uint8_t rings_scale(uint8_t c, uint8_t brightness) {
    return (uint8_t)(((unsigned)c * brightness + 127) / 255);
}

uint32_t rings_pixel_word(const rings_t *rs, int idx, ring_order_t order) {
    const ring_state_t *s = &rs->st[idx];
    uint32_t r = rings_scale(s->r, s->brightness);
    uint32_t g = rings_scale(s->g, s->brightness);
    uint32_t b = rings_scale(s->b, s->brightness);
    if (order == RING_ORDER_GRB) {
        return (g << 16) | (r << 8) | b;
    }
    return (r << 16) | (g << 8) | b;
}

int rings_render(const rings_t *rs, int idx, ring_order_t order,
                 uint32_t *words, int max_words) {
    if (idx < 0 || idx >= RING_COUNT) return -1;
    int n = rs->nleds[idx];
    if (n > max_words) return -1;
    uint32_t w = rings_pixel_word(rs, idx, order);
    for (int i = 0; i < n; i++) words[i] = w;
    return n;
}

void rings_clear_dirty(rings_t *rs, int idx) {
    if (idx >= 0 && idx < RING_COUNT) rs->dirty[idx] = false;
}
