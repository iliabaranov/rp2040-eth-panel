/*
 * ota_app.c — application-side OTA hooks (see ota_app.h).
 */
#include "ota/ota_app.h"
#include "ota/boot_state.h"
#include "ota/layout.h"

#include <stdio.h>

#include "pico/stdlib.h"
#include "hardware/watchdog.h"
#include "hardware/structs/watchdog.h"

void ota_confirm(void) {
    boot_state_t st;
    if (!boot_state_read(&st)) return;          /* USB-provisioned: nothing to confirm */
    if (st.app_valid && !st.app_confirmed) {
        st.app_confirmed = 1;
        st.boot_attempts = 0;
        boot_state_write(&st);
        printf("[ota] app confirmed healthy\n");
    }
}

void ota_request_update(void) {
    printf("[ota] update requested -> rebooting into bootloader recovery\n");
    watchdog_hw->scratch[0] = OTA_ENTER_UPDATE_MAGIC;
    sleep_ms(50);
    watchdog_reboot(0, 0, 0);
    while (1) { tight_loop_contents(); }
}
