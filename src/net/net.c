/*
 * net.c — CH9120 UART-to-Ethernet bridge driver.
 *
 * Config protocol (WCH CH9120 Serial Control Instruction Set): while CFG is held
 * LOW, each frame "0x57 0xAB <cmd> [data]" is sent at a FIXED 9600 baud and the
 * chip replies 0xAA (set commands) or the requested data (read commands 0x6x/0x81).
 * 0x0d saves to EEPROM, 0x0e executes + resets the chip. After config, UART1 is
 * switched to the data baud and becomes a transparent pipe to the TCP socket.
 *
 * IP mode is chosen explicitly at compile time (NET_USE_DHCP) — there is NO
 * auto-fallback: the CH9120 exposes no link/DHCP status the RP2040 can read (its
 * LINK pin drives the RJ45 LEDs, not a GPIO) and returns a cached IP even with no
 * cable, so a failed DHCP can't be detected. After configuring + committing, the
 * device IP is read back (0x61) for the LED octet + logging only. `dhcp_mode`
 * reflects the configured mode, not a live link.
 */
#include "net/net.h"
#include "config.h"

#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"
#include "hardware/uart.h"
#include "hardware/gpio.h"

/* CH9120 command codes */
#define CMD_VERSION    0x01
#define CMD_TCP_STATUS 0x03
#define CMD_SAVE       0x0d
#define CMD_EXEC       0x0e
#define CMD_MODE       0x10
#define CMD_LOCAL_IP   0x11
#define CMD_SUBNET     0x12
#define CMD_GATEWAY    0x13
#define CMD_LOCAL_PORT 0x14
#define CMD_BAUD       0x21
#define CMD_DHCP       0x33
#define CMD_READ_IP    0x61
#define CMD_READ_MAC   0x81

#define ACK 0xAA

static net_status_t s_status;

/* ---- low-level UART helpers ---- */
static void rx_flush(void) {
    while (uart_is_readable(CH9120_UART)) (void)uart_getc(CH9120_UART);
}

static bool rx_bytes(uint8_t *dst, int n, uint32_t timeout_ms) {
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    int i = 0;
    while (i < n && !time_reached(deadline)) {
        if (uart_is_readable(CH9120_UART)) {
            dst[i++] = uart_getc(CH9120_UART);
        } else {
            tight_loop_contents();
        }
    }
    return i == n;
}

/* Send a set/control frame and verify the 0xAA ack. */
static bool tx_cmd(uint8_t cmd, const uint8_t *payload, int n) {
    uint8_t frame[8] = { 0x57, 0xAB, cmd };
    for (int i = 0; i < n; i++) frame[3 + i] = payload[i];
    rx_flush();
    uart_write_blocking(CH9120_UART, frame, 3 + n);
    uint8_t a = 0;
    bool ok = rx_bytes(&a, 1, 200) && a == ACK;
    sleep_ms(10);
    return ok;
}

static bool tx_u8(uint8_t cmd, uint8_t v)   { return tx_cmd(cmd, &v, 1); }
static bool tx_u16(uint8_t cmd, uint16_t v) {
    uint8_t p[2] = { (uint8_t)(v & 0xFF), (uint8_t)(v >> 8) };
    return tx_cmd(cmd, p, 2);
}
static bool tx_u32(uint8_t cmd, uint32_t v) {
    uint8_t p[4] = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
    return tx_cmd(cmd, p, 4);
}

/* Send a read frame and capture n reply bytes. */
static bool rd_cmd(uint8_t cmd, uint8_t *dst, int n) {
    uint8_t frame[3] = { 0x57, 0xAB, cmd };
    rx_flush();
    uart_write_blocking(CH9120_UART, frame, 3);
    bool ok = rx_bytes(dst, n, 300);
    sleep_ms(10);
    return ok;
}

/* ---- config-mode entry/exit (config baud is always 9600) ---- */
static void enter_config(void) {
    uart_set_baudrate(CH9120_UART, CH9120_CFG_BAUD);
    gpio_put(CH9120_PIN_CFG, 0);
    sleep_ms(200);
    rx_flush();
}
static void exit_config(void) {
    gpio_put(CH9120_PIN_CFG, 1);
    sleep_ms(100);
}

/* Commit settings: save to EEPROM (acked), then execute+reset (ack may be lost
 * as the chip resets, so don't require it). */
static bool commit(void) {
    bool saved = tx_cmd(CMD_SAVE, NULL, 0);
    uint8_t frame[3] = { 0x57, 0xAB, CMD_EXEC };
    rx_flush();
    uart_write_blocking(CH9120_UART, frame, 3);
    uint8_t a; (void)rx_bytes(&a, 1, 200); /* best-effort */
    sleep_ms(300); /* chip resets */
    return saved;
}

bool net_init(net_status_t *out) {
    memset(&s_status, 0, sizeof(s_status));
    s_status.port = NET_LOCAL_PORT;

    /* UART + control pins */
    uart_init(CH9120_UART, CH9120_CFG_BAUD);
    gpio_set_function(CH9120_PIN_TX, GPIO_FUNC_UART);
    gpio_set_function(CH9120_PIN_RX, GPIO_FUNC_UART);
    uart_set_format(CH9120_UART, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(CH9120_UART, true);

    gpio_init(CH9120_PIN_CFG);
    gpio_set_dir(CH9120_PIN_CFG, GPIO_OUT);
    gpio_put(CH9120_PIN_CFG, 1);
    gpio_init(CH9120_PIN_RST);
    gpio_set_dir(CH9120_PIN_RST, GPIO_OUT);
    gpio_init(CH9120_PIN_TCPS);
    gpio_set_dir(CH9120_PIN_TCPS, GPIO_IN);
    gpio_pull_up(CH9120_PIN_TCPS);

    /* Reset pulse (active low) */
    gpio_put(CH9120_PIN_RST, 0);
    sleep_ms(50);
    gpio_put(CH9120_PIN_RST, 1);
    sleep_ms(200);

    /* Configure for the explicitly-selected mode. NOTE: the CH9120 gives no
     * link/DHCP-status the RP2040 can read (its LINK pin drives the RJ45 LEDs,
     * not a GPIO), and it returns a cached IP even with no cable — so there is no
     * reliable "DHCP failed -> fall back to static" detection. Pick the mode for
     * the deployment via NET_USE_DHCP. `dhcp_mode` reflects the *configured* mode,
     * not a live link. */
    enter_config();
    bool alive = tx_u8(CMD_MODE, NET_MODE);    /* first ack => chip is alive */
    s_status.responding = alive;
    s_status.dhcp_mode = NET_USE_DHCP ? true : false;
    tx_u8(CMD_DHCP, NET_USE_DHCP ? 1 : 0);
    tx_u16(CMD_LOCAL_PORT, NET_LOCAL_PORT);
    if (!NET_USE_DHCP) {
        static const uint8_t ip[4] = NET_LOCAL_IP;
        static const uint8_t sn[4] = NET_SUBNET;
        static const uint8_t gw[4] = NET_GATEWAY;
        tx_cmd(CMD_LOCAL_IP, ip, 4);
        tx_cmd(CMD_SUBNET, sn, 4);
        tx_cmd(CMD_GATEWAY, gw, 4);
    }
    tx_u32(CMD_BAUD, CH9120_DATA_BAUD);
    commit();
    exit_config();

    if (!alive) {
        printf("[net] CH9120 not acking — check UART1 wiring (TX20/RX21/CFG18/RST19)\n");
    }

    /* Give DHCP a moment to obtain a lease before we read the IP back (the IP is
     * informational — used for the LED octet + logging; it may be stale/unset if
     * no cable is attached). */
    if (NET_USE_DHCP) sleep_ms(4000);

    enter_config();
    rd_cmd(CMD_READ_MAC, s_status.mac, 6);
    rd_cmd(CMD_READ_IP, s_status.ip, 4);
    exit_config();

    /* Switch to the data baud — UART1 is now a transparent TCP pipe. */
    uart_set_baudrate(CH9120_UART, CH9120_DATA_BAUD);
    rx_flush();

    printf("[net] CH9120 mode=%d ipmode=%s port=%u\n",
           NET_MODE, s_status.dhcp_mode ? "DHCP" : "static", s_status.port);
    printf("[net] MAC %02X:%02X:%02X:%02X:%02X:%02X\n",
           s_status.mac[0], s_status.mac[1], s_status.mac[2],
           s_status.mac[3], s_status.mac[4], s_status.mac[5]);
    printf("[net] IP %d.%d.%d.%d  (connect: tcp %d.%d.%d.%d:%u)\n",
           s_status.ip[0], s_status.ip[1], s_status.ip[2], s_status.ip[3],
           s_status.ip[0], s_status.ip[1], s_status.ip[2], s_status.ip[3], s_status.port);

    if (out) *out = s_status;
    return s_status.responding;
}

const net_status_t *net_status(void) { return &s_status; }

void net_attach_data_mode(void) {
    uart_init(CH9120_UART, CH9120_DATA_BAUD);
    gpio_set_function(CH9120_PIN_TX, GPIO_FUNC_UART);
    gpio_set_function(CH9120_PIN_RX, GPIO_FUNC_UART);
    uart_set_format(CH9120_UART, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(CH9120_UART, true);

    gpio_init(CH9120_PIN_CFG);
    gpio_set_dir(CH9120_PIN_CFG, GPIO_OUT);
    gpio_put(CH9120_PIN_CFG, 1);   /* high = data mode (not config) */
    gpio_init(CH9120_PIN_RST);
    gpio_set_dir(CH9120_PIN_RST, GPIO_OUT);
    gpio_put(CH9120_PIN_RST, 1);   /* not in reset */
    gpio_init(CH9120_PIN_TCPS);
    gpio_set_dir(CH9120_PIN_TCPS, GPIO_IN);
    gpio_pull_up(CH9120_PIN_TCPS);

    while (uart_is_readable(CH9120_UART)) (void)uart_getc(CH9120_UART);
}

bool net_peer_connected(void) {
    return gpio_get(CH9120_PIN_TCPS) == 0; /* LOW = connected */
}

int net_read(uint8_t *buf, int max) {
    int n = 0;
    while (n < max && uart_is_readable(CH9120_UART)) {
        buf[n++] = uart_getc(CH9120_UART);
    }
    return n;
}

void net_write(const uint8_t *buf, int len) {
    uart_write_blocking(CH9120_UART, buf, (size_t)len);
}

void net_write_str(const char *s) {
    size_t n = 0;
    while (s[n]) n++;
    uart_write_blocking(CH9120_UART, (const uint8_t *)s, n);
}
