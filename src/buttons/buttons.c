/*
 * buttons.c — pure debounced button eventing (see buttons.h).
 *
 * Debounce model: a button's raw level must hold a value DIFFERENT from the
 * committed (stable) state for >= debounce_ms before the stable state flips and
 * an edge event is emitted. Any raw flicker restarts the window, so contact
 * bounce of either polarity is absorbed and edges are reported once.
 */
#include "buttons/buttons.h"

#include <string.h>

void buttons_init(buttons_t *bs, uint16_t debounce_ms) {
    memset(bs, 0, sizeof(*bs));
    bs->debounce_ms = debounce_ms;
}

void buttons_set_debounce(buttons_t *bs, uint16_t debounce_ms) {
    bs->debounce_ms = debounce_ms;
}

int buttons_update(buttons_t *bs, const bool raw[BTN_COUNT], uint32_t now_ms,
                   btn_event *evs, int max_events) {
    if (!bs->initialized) {
        /* Seed from the first snapshot: a button held at boot emits no edge. */
        for (int i = 0; i < BTN_COUNT; i++) {
            bs->stable[i] = raw[i];
            bs->raw_last[i] = raw[i];
            bs->raw_since_ms[i] = now_ms;
        }
        bs->initialized = true;
        return 0;
    }
    int ne = 0;
    for (int i = 0; i < BTN_COUNT; i++) {
        if (raw[i] != bs->raw_last[i]) {
            bs->raw_last[i] = raw[i];
            bs->raw_since_ms[i] = now_ms;
        }
        if (raw[i] != bs->stable[i] &&
            (uint32_t)(now_ms - bs->raw_since_ms[i]) >= bs->debounce_ms) {
            /* Only commit the state flip if we can also report the edge — otherwise
             * the caller would never see this transition and the debounced state
             * would silently diverge from the emitted event stream. If the buffer
             * is full, leave stable unchanged so the edge is emitted on a later
             * call (the raw level is already latched, so timing is preserved). */
            if (ne < max_events) {
                bs->stable[i] = raw[i];
                evs[ne].id = i + 1;
                evs[ne].pressed = raw[i];
                ne++;
            }
        }
    }
    return ne;
}

bool buttons_pressed(const buttons_t *bs, int idx) {
    return (idx >= 0 && idx < BTN_COUNT) ? bs->stable[idx] : false;
}
