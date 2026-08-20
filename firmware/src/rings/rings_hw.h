/*
 * rings_hw.h — GLUE: PIO state machines driving the two WS2812 rings.
 *
 * Uses pio1 (the status LED owns pio0) with one shared ws2812 program and one
 * state machine per ring: sm0 -> RING1_PIN, sm1 -> RING2_PIN, 800 kHz.
 */
#ifndef PANEL_RINGS_HW_H
#define PANEL_RINGS_HW_H

#include <stdint.h>

void rings_hw_init(void);

/* Push one frame (count pixel words, wire order already packed by rings.c) to
 * ring idx. Blocking on the PIO FIFO; ~30 us per LED at 800 kHz. The WS2812
 * latch (>50 us low) is satisfied by the super-loop tick between pushes. */
void rings_hw_push(int idx, const uint32_t *words, int count);

#endif /* PANEL_RINGS_HW_H */
