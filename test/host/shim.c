/*
 * shim.c — thin host-test wrappers around the pure firmware modules.
 *
 * Exposes buttons/rings/protocol via flat int/pointer signatures so the pytest
 * suite can drive them through ctypes without mirroring C struct layouts. The
 * modules themselves are compiled unchanged (same .c used in the firmware).
 *
 * Tests feed raw button levels and a synthetic millisecond clock here.
 */
#include "buttons/buttons.h"
#include "protocol/protocol.h"
#include "rings/rings.h"

#include <stdlib.h>

/* ---- buttons ---- */
buttons_t *bt_new(int debounce_ms) {
    buttons_t *b = malloc(sizeof *b);
    buttons_init(b, (uint16_t)debounce_ms);
    return b;
}
void bt_free(buttons_t *b) { free(b); }

void bt_set_debounce(buttons_t *b, int debounce_ms) {
    buttons_set_debounce(b, (uint16_t)debounce_ms);
}

/* Returns event count; fills parallel id/pressed arrays (caller sizes >= max). */
int bt_update(buttons_t *b, int raw0, int raw1, uint32_t now_ms,
              int *ids, int *pressed, int max) {
    bool raw[BTN_COUNT] = { raw0 != 0, raw1 != 0 };
    btn_event ev[BTN_COUNT];
    int cap = max < BTN_COUNT ? max : BTN_COUNT;
    int n = buttons_update(b, raw, now_ms, ev, cap);
    for (int i = 0; i < n; i++) {
        ids[i] = ev[i].id;
        pressed[i] = ev[i].pressed ? 1 : 0;
    }
    return n;
}

int bt_pressed(const buttons_t *b, int idx) {
    return buttons_pressed(b, idx) ? 1 : 0;
}

int bt_count(void) { return BTN_COUNT; }

/* ---- rings ---- */
rings_t *rg_new(int nleds0, int nleds1) {
    rings_t *r = malloc(sizeof *r);
    uint16_t nleds[RING_COUNT] = { (uint16_t)nleds0, (uint16_t)nleds1 };
    rings_init(r, nleds);
    return r;
}
void rg_free(rings_t *r) { free(r); }

int rg_set(rings_t *rs, int idx, int r, int g, int b, int brightness) {
    return rings_set(rs, idx, r, g, b, brightness) ? 1 : 0;
}

int rg_scale(int c, int brightness) {
    return (int)rings_scale((uint8_t)c, (uint8_t)brightness);
}

uint32_t rg_pixel_word(const rings_t *rs, int idx, int order) {
    return rings_pixel_word(rs, idx, (ring_order_t)order);
}

/* Fills words[] with the rendered frame; returns count or -1 (see rings.h). */
int rg_render(const rings_t *rs, int idx, int order,
              uint32_t *words, int max_words) {
    return rings_render(rs, idx, (ring_order_t)order, words, max_words);
}

int rg_dirty(const rings_t *rs, int idx) {
    return (idx >= 0 && idx < RING_COUNT && rs->dirty[idx]) ? 1 : 0;
}
void rg_clear_dirty(rings_t *rs, int idx) { rings_clear_dirty(rs, idx); }

int rg_count(void) { return RING_COUNT; }

/* ---- protocol ---- */
/* Explodes proto_cmd into scalar out-params. Returns 1 if a "cmd" field was
 * found (proto_parse's bool), 0 otherwise. */
int pp_parse(const char *line, int *type, int *id, int *r, int *g, int *b,
             int *brightness, int *on, int *debounce_ms) {
    proto_cmd c;
    bool found = proto_parse(line, &c);
    *type = (int)c.type;
    *id = c.id;
    *r = c.r;
    *g = c.g;
    *b = c.b;
    *brightness = c.brightness;
    *on = c.on;
    *debounce_ms = c.debounce_ms;
    return found ? 1 : 0;
}

/* Formatters: write into the caller's buffer; return strlen or -1 (truncation). */
int pf_btn(char *buf, int n, int id, int pressed, uint32_t ms) {
    return proto_fmt_btn(buf, (size_t)n, id, pressed != 0, ms);
}
int pf_hello(char *buf, int n, const char *fw, int nleds0, int nleds1,
             int pressed0, int pressed1, const char *ip) {
    uint16_t nleds[2] = { (uint16_t)nleds0, (uint16_t)nleds1 };
    bool pressed[2] = { pressed0 != 0, pressed1 != 0 };
    return proto_fmt_hello(buf, (size_t)n, fw, nleds, pressed, ip);
}
int pf_ack(char *buf, int n, const char *cmd) {
    return proto_fmt_ack(buf, (size_t)n, cmd);
}
int pf_err(char *buf, int n, const char *msg) {
    return proto_fmt_err(buf, (size_t)n, msg);
}
