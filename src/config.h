/*
 * config.h — compile-time defaults for rp2040-eth-panel.
 *
 * Board: Waveshare RP2040-ETH. Ethernet is provided by a CH9120 UART-to-Ethernet
 * bridge (NOT a W5500/SPI). The RP2040 configures the CH9120 over UART1 in config
 * mode, then streams the TCP payload over the same UART at the data baud.
 *
 * Panel hardware: two momentary buttons (button 1 is illuminated), one lamp
 * output for button 1's illumination, and two WS2812 LED rings.
 */
#ifndef PANEL_CONFIG_H
#define PANEL_CONFIG_H

#define FW_VERSION "1.0.1"

/* ---- CH9120 Ethernet bridge (UART1) — fixed by the Waveshare board ---- */
#define CH9120_UART       uart1
#define CH9120_PIN_TX     20 /* RP2040 UART1 TX -> CH9120 RXD */
#define CH9120_PIN_RX     21 /* RP2040 UART1 RX <- CH9120 TXD */
#define CH9120_PIN_CFG    18 /* config enable: LOW = config mode */
#define CH9120_PIN_RST    19 /* reset, active LOW */
#define CH9120_PIN_TCPS   17 /* TCP status: LOW = peer connected */
#define CH9120_CFG_BAUD   9600
#define CH9120_DATA_BAUD  115200

/* ---- Network role + addressing ---- */
#define NET_MODE_TCP_SERVER 0
#define NET_MODE_TCP_CLIENT 1
#define NET_MODE_UDP_SERVER 2
#define NET_MODE_UDP_CLIENT 3

#define NET_MODE        NET_MODE_TCP_SERVER /* device listens; host connects */
/* IP mode for the deployment. 1 = DHCP, 0 = static (the addresses below).
 * There is no auto-fallback: the CH9120 gives no link/DHCP status the RP2040 can
 * read, so a failed DHCP can't be detected — choose the right mode here. */
#define NET_USE_DHCP    1

/* Static addressing — used when NET_USE_DHCP = 0. (With DHCP these are ignored;
 * the leased IP is read back from the CH9120 and shown on serial / the LED octet.) */
#define NET_LOCAL_IP    { 10, 74, 31, 251 }   /* set for your subnet if using static */
#define NET_SUBNET      { 255, 255, 252, 0 }  /* /22 */
#define NET_GATEWAY     { 10, 74, 28, 1 }
#define NET_LOCAL_PORT  5005

/* Target (used only in TCP/UDP client mode — device dials this host). */
#define NET_TARGET_IP   { 192, 168, 1, 100 }
#define NET_TARGET_PORT 5005

/* ---- Application pins ----
 * NOTE: the RP2040-ETH MINI board only breaks out GPIO0-9, 22, 26, 27, 28 on its
 * 24-pin header (GP10-15 and GP25 are NOT on the header; GP16-21 are the CH9120).
 * All panel pins below are header-accessible. Silk labels are GPn. */
#define RING1_PIN      2  /* WS2812 ring 1 data (header pin 21) */
#define RING2_PIN      3  /* WS2812 ring 2 data (header pin 20) */
#define BUTTON1_PIN    4  /* illuminated button, to GND, internal pull-up (pin 19) */
#define BUTTON2_PIN    5  /* plain button, to GND, internal pull-up (pin 18) */
#define LAMP_PIN       6  /* button 1 illumination, on/off output (header pin 16) */
#define STATUS_LED_PIN 25 /* onboard WS2812 (GP25, not on header) */

/* ---- WS2812 rings ----
 * Color order is per-chain: the ONBOARD GP25 WS2812 on this board latches RGB
 * (verified by self-test in the keypad project — status_led.c sends RGB), but
 * standard WS2812B ring modules latch GRB. If colors come out swapped, build
 * with -DRING_SELFTEST=1, watch the announced colors, and flip this. */
#define RING1_NUM_LEDS 16
#define RING2_NUM_LEDS 16
#define RING_MAX_LEDS  16          /* max(RING1_NUM_LEDS, RING2_NUM_LEDS) */
#define RING_COLOR_ORDER_GRB 1     /* 1 = GRB (standard WS2812B), 0 = RGB */

/* Power-on ring state: off, full brightness scale so the first color command
 * with no explicit brightness shows at full. */
#define RING_DEFAULT_BRIGHTNESS 255

/* ---- Buttons ---- */
#define BUTTON_COUNT            2
#define DEBOUNCE_MS_DEFAULT     30 /* runtime-overridable via the `config` command */

#endif /* PANEL_CONFIG_H */
