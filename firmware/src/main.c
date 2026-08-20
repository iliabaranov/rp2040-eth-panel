/*
 * rp2040-eth-panel — application entry point (Waveshare RP2040-ETH).
 *
 * Two-button / dual-WS2812-ring operator panel. Brings up the CH9120 Ethernet
 * bridge, indicates state on the onboard WS2812 (green=DHCP / amber=static,
 * flashing the IP's last octet), confirms the running image to the bootloader,
 * then runs the super-loop: debounce the buttons and stream press/release events
 * as JSON to the TCP client, execute ring/lamp/config commands, and handle the
 * `{"cmd":"ota"}` trigger (reboot into OTA recovery).
 *
 * On each TCP peer connect (TCPS pin edge) the device sends a hello line with
 * firmware version, ring sizes, and the current button states, so the host can
 * resync state after either side restarts. Hosts should also request it with
 * {"cmd":"hello"} after connecting: some CH9120 batches never assert TCPS, so
 * the unsolicited hello may never arrive.
 */
#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"

#include "config.h"
#include "net/net.h"
#include "status_led/status_led.h"
#include "ota/ota_app.h"
#include "buttons/buttons.h"
#include "buttons/buttons_hw.h"
#include "rings/rings.h"
#include "rings/rings_hw.h"
#include "protocol/protocol.h"

#if RING_COLOR_ORDER_GRB
#define RING_ORDER RING_ORDER_GRB
#else
#define RING_ORDER RING_ORDER_RGB
#endif

static rings_t    s_rings;
static buttons_t  s_buttons;
static uint16_t   s_debounce_ms = DEBOUNCE_MS_DEFAULT;

/* Push any dirty ring frames. The 2 ms loop tick between passes satisfies the
 * WS2812 >50 us inter-frame latch. */
static void rings_flush(void) {
    uint32_t words[RING_MAX_LEDS];
    for (int i = 0; i < RING_COUNT; i++) {
        if (!s_rings.dirty[i]) continue;
        int n = rings_render(&s_rings, i, RING_ORDER, words, RING_MAX_LEDS);
        if (n < 0) continue; /* render failed (LED count > RING_MAX_LEDS) — keep
                              * dirty so a corrected frame still gets pushed later */
        rings_hw_push(i, words, n);
        rings_clear_dirty(&s_rings, i);
    }
}

static void send_line(const char *line, int len) {
    if (len > 0) net_write((const uint8_t *)line, len);
}

static void send_ack(const char *cmd) {
    char line[48];
    send_line(line, proto_fmt_ack(line, sizeof(line), cmd));
}

static void send_err(const char *msg) {
    char line[80];
    send_line(line, proto_fmt_err(line, sizeof(line), msg));
}

static void send_hello(const net_status_t *st) {
    char ip[16];
    snprintf(ip, sizeof(ip), "%d.%d.%d.%d", st->ip[0], st->ip[1], st->ip[2], st->ip[3]);
    const uint16_t nleds[2] = { RING1_NUM_LEDS, RING2_NUM_LEDS };
    const bool pressed[2] = { buttons_pressed(&s_buttons, 0),
                              buttons_pressed(&s_buttons, 1) };
    char line[160];
    send_line(line, proto_fmt_hello(line, sizeof(line), FW_VERSION, nleds, pressed, ip));
}

static void dispatch(const char *line) {
    proto_cmd c;
    if (!proto_parse(line, &c)) {
        send_err("no cmd");
        return;
    }
    switch (c.type) {
    case CMD_RING:
        if (rings_set(&s_rings, c.id - 1, c.r, c.g, c.b, c.brightness)) {
            send_ack("ring");
        } else {
            send_err("bad ring cmd");
        }
        break;
    case CMD_LAMP:
        if (c.on == 0 || c.on == 1) {
            lamp_hw_set(c.on == 1);
            send_ack("lamp");
        } else {
            send_err("bad lamp cmd");
        }
        break;
    case CMD_CONFIG:
        if (c.debounce_ms >= 1 && c.debounce_ms <= 1000) {
            s_debounce_ms = (uint16_t)c.debounce_ms;
            buttons_set_debounce(&s_buttons, s_debounce_ms);
            send_ack("config");
        } else {
            send_err("bad debounce_ms");
        }
        break;
    case CMD_PING:
        send_ack("ping");
        break;
    case CMD_HELLO:
        /* Host-requested hello. The reply IS the hello line (no ack). Needed
         * because some CH9120 batches never assert TCPS, so the edge-triggered
         * hello below cannot be relied on by hosts. */
        send_hello(net_status());
        break;
    case CMD_OTA:
        send_ack("ota");
        sleep_ms(50);          /* let the ack drain through the CH9120 */
        ota_request_update();  /* reboots into bootloader recovery */
        break;
    default:
        send_err("unknown cmd");
        break;
    }
}

int main(void) {
    stdio_init_all();

    /* Let the USB-serial host attach before the banner. */
    sleep_ms(1500);
    printf("\n=== rp2040-eth-panel v%s (CH9120) ===\n", FW_VERSION);

    /* Bring the LED up FIRST as a boot indicator: solid blue once we reach main
     * (so "dark" means hung in crt0/jump, not merely mid-net_init which can take
     * ~20s). Switches to the IP-octet flash once the network is up. */
    status_led_init();
    status_led_solid(0, 0, 60); /* blue: booted, bringing up network */

    buttons_hw_init();
    buttons_init(&s_buttons, s_debounce_ms);
    rings_hw_init();
    const uint16_t nleds[RING_COUNT] = { RING1_NUM_LEDS, RING2_NUM_LEDS };
    rings_init(&s_rings, nleds);
    rings_flush(); /* push a known all-off frame over any power-on garbage */

#ifndef RING_SELFTEST
#define RING_SELFTEST 0
#endif
#if RING_SELFTEST
    /* Panel hardware self-test, no network: cycle pure logical R/G/B on both
     * rings with distinct dwell times (RED 1s, GREEN 2s, BLUE 4s) to verify the
     * color order; print raw button levels; lamp follows button 1. */
    {
        const char *names[3] = {"RED (1s)", "GREEN (2s)", "BLUE (4s)"};
        const uint8_t cols[3][3] = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}};
        const uint32_t dwell[3] = {1000, 2000, 4000};
        int i = 0;
        absolute_time_t next = get_absolute_time();
        while (true) {
            if (time_reached(next)) {
                printf("[ringtest] intended %s\n", names[i]);
                for (int rg = 0; rg < RING_COUNT; rg++)
                    rings_set(&s_rings, rg, cols[i][0], cols[i][1], cols[i][2], 255);
                next = make_timeout_time_ms(dwell[i]);
                i = (i + 1) % 3;
            }
            rings_flush();
            bool raw[BTN_COUNT];
            buttons_hw_read(raw);
            lamp_hw_set(raw[0]);
            static bool last[BTN_COUNT];
            for (int bi = 0; bi < BTN_COUNT; bi++) {
                if (raw[bi] != last[bi]) {
                    printf("[ringtest] button %d raw %s\n", bi + 1, raw[bi] ? "DOWN" : "UP");
                    last[bi] = raw[bi];
                }
            }
            sleep_ms(2);
        }
    }
#endif

    net_status_t st;
    net_init(&st);

    /* Color = configured IP mode (green = DHCP, amber = static). NOTE: this does
     * NOT indicate a live Ethernet link — the CH9120 exposes no link status to the
     * RP2040, so the LED only reflects "app running + configured mode + last IP". */
    if (st.dhcp_mode) {
        status_led_set_color(0, 40, 0);  /* green: DHCP mode */
    } else {
        status_led_set_color(40, 20, 0); /* amber: static mode */
    }
    status_led_show_octet(st.ip[3]);
    printf("[main] app running (%s, ip .%d) — note: LED does not indicate link state\n",
           st.dhcp_mode ? "DHCP" : "static", st.ip[3]);

    /* We booted far enough to bring the network up -> confirm this image so the
     * bootloader stops counting attempts and won't revert to recovery. */
    if (st.responding) {
        ota_confirm();
    }

    printf("[main] panel up: buttons GP%d/GP%d, lamp GP%d, rings GP%d/GP%d (%d/%d LEDs)\n",
           BUTTON1_PIN, BUTTON2_PIN, LAMP_PIN, RING1_PIN, RING2_PIN,
           RING1_NUM_LEDS, RING2_NUM_LEDS);

    /* Seed the debouncer from the current pin levels BEFORE the loop, so the very
     * first hello (which can fire on the same iteration as the first peer connect)
     * reports the true button state — e.g. a button held across a reboot/OTA. The
     * seeding update emits no edge events (by design); state reaches the host via
     * hello and any later release/press then produces a normal edge. */
    {
        bool raw0[BTN_COUNT];
        buttons_hw_read(raw0);
        buttons_update(&s_buttons, raw0, to_ms_since_boot(get_absolute_time()), NULL, 0);
    }

    bool      peer_was_connected = false;
    char      linebuf[256];
    size_t    linelen = 0;
    bool      discard = false; /* true while skipping an overlong line to its '\n' */
    uint8_t   rxbuf[128];
    btn_event evs[BTN_COUNT * 2];

    while (true) {
        status_led_task();

        /* Hello on every TCP peer connect so the host can resync state. */
        bool peer = net_peer_connected();
        if (peer && !peer_was_connected) {
            net_rx_flush();    /* drop stale bytes left by the previous client */
            send_hello(&st);
            linelen = 0;       /* drop any half-line from a previous connection */
            discard = false;
        }
        peer_was_connected = peer;

        /* Buttons: sample -> debounce -> press/release events to wire + serial. */
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        bool raw[BTN_COUNT];
        buttons_hw_read(raw);
        int ne = buttons_update(&s_buttons, raw, now_ms, evs,
                                (int)(sizeof(evs) / sizeof(evs[0])));
        for (int i = 0; i < ne; i++) {
            char line[64];
            send_line(line, proto_fmt_btn(line, sizeof(line), evs[i].id,
                                          evs[i].pressed, now_ms));
            printf("[btn] %d %s\n", evs[i].id, evs[i].pressed ? "down" : "up");
        }

        /* Incoming commands: accumulate bytes, dispatch complete lines. */
        int n = net_read(rxbuf, (int)sizeof(rxbuf));
        for (int i = 0; i < n; i++) {
            char ch = (char)rxbuf[i];
            if (ch == '\n') {
                /* Newline ends a line — or ends an overlong line we were skipping.
                 * Either way, resync to a clean line boundary here. */
                if (!discard) {
                    linebuf[linelen] = '\0';
                    if (linelen > 0) dispatch(linebuf);
                }
                linelen = 0;
                discard = false;
            } else if (discard) {
                /* Mid-overlong-line: keep skipping until the next newline so a
                 * trailing fragment can never be dispatched as a command. */
            } else if (linelen < sizeof(linebuf) - 1) {
                linebuf[linelen++] = ch;
            } else {
                /* Overflow: enter discard until the next newline (emit one err). */
                discard = true;
                linelen = 0;
                send_err("line too long");
            }
        }

        rings_flush();
        sleep_ms(2);
    }
}
