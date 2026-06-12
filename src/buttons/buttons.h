/*
 * buttons.h — PURE debounced button eventing (no hardware, no SDK calls).
 *
 * Per-button debounce with press/release edge events. Time is injected as
 * tick_ms and raw levels are passed in by the caller, so the logic runs
 * identically on host (pytest/ctypes) and target. Mirrors the keypad project's
 * pure-logic/glue split.
 */
#ifndef PANEL_BUTTONS_H
#define PANEL_BUTTONS_H

#include <stdbool.h>
#include <stdint.h>

#define BTN_COUNT 2

typedef struct {
    int  id;      /* 1-based button id */
    bool pressed; /* true = down edge, false = up edge */
} btn_event;

typedef struct {
    bool     stable[BTN_COUNT];     /* debounced state, true = pressed */
    bool     raw_last[BTN_COUNT];   /* last raw sample */
    uint32_t raw_since_ms[BTN_COUNT]; /* when the raw level last changed */
    uint16_t debounce_ms;
} buttons_t;

/* Initialize: all buttons released, raw history seeded as released. */
void buttons_init(buttons_t *bs, uint16_t debounce_ms);

/* Change the debounce window at runtime (applies from the next sample). */
void buttons_set_debounce(buttons_t *bs, uint16_t debounce_ms);

/* Feed one raw sample per button (true = pressed) at time now_ms. Emits up to
 * max_events edge events for buttons whose raw level has held a NEW value for
 * >= debounce_ms. Returns the number of events written. */
int buttons_update(buttons_t *bs, const bool raw[BTN_COUNT], uint32_t now_ms,
                   btn_event *evs, int max_events);

/* Current debounced state of button idx (0-based). */
bool buttons_pressed(const buttons_t *bs, int idx);

#endif /* PANEL_BUTTONS_H */
