/*
 * buttons_hw.h — GLUE: GPIO for the two panel buttons and the button-1 lamp.
 */
#ifndef PANEL_BUTTONS_HW_H
#define PANEL_BUTTONS_HW_H

#include <stdbool.h>

#include "buttons/buttons.h"

/* Button inputs (internal pull-ups, active-low) + lamp output (off). */
void buttons_hw_init(void);

/* Sample the raw button levels (true = pressed, i.e. pin pulled low). */
void buttons_hw_read(bool raw[BTN_COUNT]);

/* Button 1 illumination on/off. */
void lamp_hw_set(bool on);
bool lamp_hw_get(void);

#endif /* PANEL_BUTTONS_HW_H */
