/*
 * bootloader/main.c — immutable first-stage bootloader at flash base (0x10000000).
 *
 * On boot it either hands off to the application in the slot, or enters network
 * recovery (the OTA receiver) when the app is invalid/unconfirmed or an update was
 * requested by the app. The boot path touches no USB and minimal hardware for a
 * fast, clean hand-off (the app's IRQ-driven init then works); USB stdio is brought
 * up only in recovery (which always ends in a full reset). See docs/OTA.md.
 *
 * This stage is provisioned once over USB and is never overwritten by OTA, so a
 * failed update can never remove the ability to re-flash over Ethernet.
 */
#include <stdio.h>

#include "pico/stdlib.h"
#include "hardware/structs/scb.h"
#include "hardware/structs/watchdog.h"
#include "hardware/resets.h"

#include "ota/layout.h"
#include "ota/crc32.h"
#include "ota/boot_state.h"

#define BL_VERSION "1.0.0"

#define RAM_START 0x20000000u
#define RAM_END   0x20042000u

void recovery_run(void); /* recovery.c (never returns) */

static bool app_vectortable_sane(uint32_t vtable) {
    uint32_t sp = ((const uint32_t *)vtable)[0];
    uint32_t pc = ((const uint32_t *)vtable)[1];
    if (sp < RAM_START || sp > RAM_END) return false;
    if (pc < APP_XIP_ADDR || pc >= APP_XIP_ADDR + APP_MAX_SIZE) return false;
    if ((pc & 1u) == 0) return false; /* Thumb bit */
    return true;
}

/* ARMv6-M core registers (clear interrupt/SysTick state before the jump). */
#define SYSTICK_CSR (*(volatile uint32_t *)0xE000E010u)
#define NVIC_ICER   (*(volatile uint32_t *)0xE000E180u)
#define NVIC_ICPR   (*(volatile uint32_t *)0xE000E280u)

/* Put peripherals back in reset (except those needed to keep running / XIP) so the
 * app starts from a cold-boot-like state. */
static void reset_peripherals(void) {
    reset_block(~(RESETS_RESET_IO_QSPI_BITS |
                  RESETS_RESET_PADS_QSPI_BITS |
                  RESETS_RESET_PLL_USB_BITS |
                  RESETS_RESET_USBCTRL_BITS |
                  RESETS_RESET_SYSCFG_BITS |
                  RESETS_RESET_PLL_SYS_BITS));
}

static void __attribute__((noreturn)) jump_to_app(uint32_t vtable) {
    uint32_t sp = ((const uint32_t *)vtable)[0];
    uint32_t pc = ((const uint32_t *)vtable)[1];

    /* Disable individual IRQs + SysTick, but DO NOT set PRIMASK (cpsid i): the
     * app's early init (stdio/sleep_ms) needs the timer-alarm IRQ, so interrupts
     * must stay globally enabled. No peripheral IRQ is enabled here. */
    SYSTICK_CSR = 0;
    NVIC_ICER = 0xFFFFFFFFu;
    NVIC_ICPR = 0xFFFFFFFFu;
    reset_peripherals();

    scb_hw->vtor = vtable;
    __asm volatile("msr msp, %0" : : "r"(sp));
    __asm volatile("bx %0" : : "r"(pc));
    while (1) { tight_loop_contents(); }
}

/* Decide whether to boot the app slot. Returns false -> enter recovery. */
static bool decide_boot_app(void) {
    uint32_t scratch = watchdog_hw->scratch[0];
    watchdog_hw->scratch[0] = 0;
    if (scratch == OTA_ENTER_UPDATE_MAGIC) return false; /* app requested update */

    boot_state_t st;
    if (!boot_state_read(&st)) {
        /* No boot-state (USB-provisioned): trust a sane vector table. */
        return app_vectortable_sane(APP_VTABLE_ADDR);
    }
    if (!st.app_valid || !app_vectortable_sane(APP_VTABLE_ADDR)) return false;
    if (ota_crc32((const uint8_t *)APP_XIP_ADDR, st.app_len) != st.app_crc32) return false;
    if (st.app_confirmed) return true;
    if (st.boot_attempts < OTA_MAX_BOOT_ATTEMPTS) {
        st.boot_attempts++;
        boot_state_write(&st);
        return true;
    }
    /* Valid image that never confirmed after N boots -> drop to recovery. */
    st.app_valid = 0;
    boot_state_write(&st);
    return false;
}

int main(void) {
    if (decide_boot_app()) {
        jump_to_app(APP_VTABLE_ADDR); /* fast path: USB untouched */
    }

    /* Recovery: now it's safe to bring up USB stdio for diagnostics. */
    stdio_init_all();
    printf("\n=== rp2040-eth-panel bootloader v%s (recovery) ===\n", BL_VERSION);
    recovery_run(); /* CH9120 OTA receiver; ends in a watchdog reset */
    while (1) { tight_loop_contents(); }
}
