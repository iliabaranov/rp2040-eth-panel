/*
 * net.h — CH9120 UART-to-Ethernet bridge driver (Waveshare RP2040-ETH).
 *
 * net_init() resets and configures the CH9120 over UART1 (config mode, fixed 9600
 * baud) for the mode selected in config.h (TCP server; DHCP or static per
 * NET_USE_DHCP), reads back the IP for display, then switches UART1 to the data
 * baud, where the CH9120 transparently bridges UART1 <-> the TCP socket.
 *
 * There is intentionally NO DHCP-vs-static auto-fallback: the CH9120 exposes no
 * link/DHCP status to the RP2040 (its LINK pin drives the RJ45 LEDs, not a GPIO)
 * and returns a cached IP even with no cable, so "DHCP failed" can't be detected.
 * Choose the mode for the deployment via NET_USE_DHCP.
 */
#ifndef PANEL_NET_H
#define PANEL_NET_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    bool    responding; /* CH9120 acked config commands (chip alive / wired) */
    bool    dhcp_mode;  /* configured mode: true = DHCP, false = static. NOT a live
                         * link/lease indication (the CH9120 exposes none). */
    uint8_t ip[4];      /* IP read back from the CH9120 (informational; may be stale
                         * if no cable is attached) */
    uint8_t mac[6];
    uint16_t port;
} net_status_t;

/* Reset + configure the CH9120 and enter data mode. Fills *status (may be NULL). */
bool net_init(net_status_t *status);

/* Lightweight attach WITHOUT reconfiguring the CH9120: just bring UART1 up at the
 * data baud and set the control pins to data mode. The CH9120 keeps its config
 * (mode/IP/DHCP lease) across an RP2040-only reboot, so recovery can reuse it —
 * fast (<1s) and keeps the same IP. Assumes the CH9120 was already configured. */
void net_attach_data_mode(void);

const net_status_t *net_status(void);

/* TCPS pin: true when a TCP peer is connected (pin is LOW). */
bool net_peer_connected(void);

/* Non-blocking read of up to max bytes from the TCP stream. Returns count. */
int net_read(uint8_t *buf, int max);

/* Discard any buffered inbound bytes (RX ring + UART FIFO). Use on a new peer
 * connection so a stale line from the previous client can't be mis-dispatched. */
void net_rx_flush(void);

/* Write len bytes to the TCP stream (blocking on the UART FIFO). */
void net_write(const uint8_t *buf, int len);

/* Convenience: write a NUL-terminated string. */
void net_write_str(const char *s);

#endif /* PANEL_NET_H */
