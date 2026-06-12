cmake_minimum_required(VERSION 3.13)

# Pull in the Pico SDK (uses PICO_SDK_PATH from the environment).
include(pico_sdk_import.cmake)

project(rp2040_eth_panel C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# The Waveshare RP2040-ETH is a plain RP2040 board (Ethernet is a CH9120 UART bridge,
# not SPI), so the stock "pico" board config matches the core and onboard WS2812 (GP25).
if(NOT DEFINED PICO_BOARD)
    set(PICO_BOARD pico)
endif()

pico_sdk_init()

# The Waveshare RP2040-ETH has a 4 MB W25Q32 (the default "pico" board assumes
# 2 MB). The flash API hard_asserts offset+count <= PICO_FLASH_SIZE_BYTES, so the
# boot-state sectors near the top of flash (0x3FE000) would panic without this.
add_compile_definitions(PICO_FLASH_SIZE_BYTES=4194304)

# ---- Application ----
# Ethernet on the Waveshare RP2040-ETH is a CH9120 UART<->Ethernet bridge driven
# over UART1 (see src/net/net.c) — no external Ethernet library is required.
add_executable(panel
    src/main.c
    src/net/net.c
    src/status_led/status_led.c
    src/buttons/buttons.c
    src/buttons/buttons_hw.c
    src/rings/rings.c
    src/rings/rings_hw.c
    src/protocol/protocol.c
    src/ota/crc32.c
    src/ota/boot_state.c
    src/ota/ota_app.c
)
target_include_directories(panel PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

# Generate the WS2812 PIO header (ws2812.pio.h) into the build include path.
pico_generate_pio_header(panel ${CMAKE_CURRENT_LIST_DIR}/src/status_led/ws2812.pio)

target_link_libraries(panel
    pico_stdlib
    hardware_uart
    hardware_pio
    hardware_flash
)

# Test hook: -DRING_SELFTEST=1 skips networking and cycles pure R/G/B on both
# rings (to map their byte order), echoes raw button levels on serial, and
# drives the lamp from button 1.
if(RING_SELFTEST)
    target_compile_definitions(panel PRIVATE RING_SELFTEST=1)
endif()

# Link the application into the offset slot (0x10040000) so the bootloader can
# hand off to it. -DAPP_STANDALONE=1 instead links at flash base 0x10000000 for a
# no-bootloader build (recovery / known-good baseline).
if(NOT APP_STANDALONE)
    pico_set_linker_script(panel ${CMAKE_CURRENT_LIST_DIR}/linker/app_memmap.ld)
endif()

# USB serial for bring-up logging; disable UART stdio (no console wired yet).
pico_enable_stdio_usb(panel 1)
pico_enable_stdio_uart(panel 0)

# Generate .uf2 / .bin / .hex etc.
pico_add_extra_outputs(panel)

# ---- Bootloader (immutable first stage at flash base 0x10000000) ----
add_executable(bootloader
    bootloader/main.c
    bootloader/recovery.c
    src/ota/crc32.c
    src/ota/boot_state.c
    src/net/net.c
    src/status_led/status_led.c
)
target_include_directories(bootloader PRIVATE ${CMAKE_CURRENT_LIST_DIR}/src)
pico_generate_pio_header(bootloader ${CMAKE_CURRENT_LIST_DIR}/src/status_led/ws2812.pio)
target_link_libraries(bootloader
    pico_stdlib
    hardware_resets
    hardware_structs
    hardware_flash
    hardware_uart
    hardware_pio
)
# Cap the bootloader to its 256 KB region (build fails if it overflows).
pico_set_linker_script(bootloader ${CMAKE_CURRENT_LIST_DIR}/linker/bootloader_memmap.ld)
pico_enable_stdio_usb(bootloader 1)
pico_enable_stdio_uart(bootloader 0)
pico_add_extra_outputs(bootloader)

# ---- apptest: minimal offset-slot app to isolate the bootloader jump ----
add_executable(apptest
    apptest/main.c
    src/status_led/status_led.c
)
target_include_directories(apptest PRIVATE ${CMAKE_CURRENT_LIST_DIR}/src)
pico_generate_pio_header(apptest ${CMAKE_CURRENT_LIST_DIR}/src/status_led/ws2812.pio)
target_link_libraries(apptest pico_stdlib hardware_pio)
pico_set_linker_script(apptest ${CMAKE_CURRENT_LIST_DIR}/linker/app_memmap.ld)
pico_enable_stdio_usb(apptest 1)
pico_enable_stdio_uart(apptest 0)
pico_add_extra_outputs(apptest)
