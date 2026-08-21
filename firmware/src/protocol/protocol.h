/*
 * protocol.h — pure line-delimited JSON protocol (no hardware).
 *
 * Device->host events and host->device commands, one JSON object per '\n' line.
 * Event formatters write a complete line (incl. trailing '\n'); the command
 * parser extracts the fields of the small fixed command set. Host-testable.
 *
 * Device -> host:
 *   {"t":"hello","fw":"1.0.0","buttons":2,"rings":[16,16],"pressed":[false,false],"ip":"10.74.29.12"}
 *   {"t":"btn","id":1,"e":"down","ms":123456}
 *   {"t":"btn","id":1,"e":"up","ms":124102}
 *   {"t":"ack","cmd":"ring"}
 *   {"t":"err","msg":"bad ring cmd"}
 *
 * Host -> device:
 *   {"cmd":"ring","id":1,"r":255,"g":64,"b":0,"brightness":128}   (absent fields keep current)
 *   {"cmd":"lamp","on":true}                                      (button 1 illumination)
 *   {"cmd":"config","debounce_ms":30}
 *   {"cmd":"ping"}
 *   {"cmd":"hello"}                                               (reply = the hello line)
 *   {"cmd":"ota"}                                                 (reboot into OTA recovery)
 *
 * The hello line is sent unsolicited on each TCP peer connect (TCPS pin edge),
 * but some CH9120 batches never assert TCPS, so hosts must not rely on it:
 * request it with {"cmd":"hello"} if none arrives shortly after connecting.
 * The reply is the hello event line itself, not an ack. Do NOT send the
 * request in the same instant as the connect — on TCPS-working units the
 * device flushes its RX buffer at the connect edge and can truncate a line
 * already in flight.
 */
#ifndef PANEL_PROTOCOL_H
#define PANEL_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* ---- Device -> host events. Return strlen written, or -1 on truncation. ---- */
int proto_fmt_btn(char *buf, size_t n, int id, bool pressed, uint32_t ms);
int proto_fmt_hello(char *buf, size_t n, const char *fw, const uint16_t nleds[2],
                    const bool pressed[2], const char *ip);
int proto_fmt_ack(char *buf, size_t n, const char *cmd);
int proto_fmt_err(char *buf, size_t n, const char *msg);

/* ---- Host -> device commands ---- */
typedef enum {
    CMD_NONE = 0,
    CMD_RING,
    CMD_LAMP,
    CMD_CONFIG,
    CMD_PING,
    CMD_OTA,
    CMD_HELLO,
    CMD_UNKNOWN,
} proto_cmd_type;

typedef struct {
    proto_cmd_type type;
    /* ring */
    int id;          /* 1-based ring id, or -1 if absent */
    int r, g, b;     /* 0..255, or -1 if absent (absent = keep current) */
    int brightness;  /* 0..255, or -1 if absent (absent = keep current) */
    /* lamp */
    int on;          /* 1 / 0, or -1 if absent */
    /* config */
    int debounce_ms; /* or -1 */
} proto_cmd;

/* Parse one JSON command line. Returns true if a "cmd" field was found
 * (type set accordingly; CMD_UNKNOWN for unrecognized verbs). */
bool proto_parse(const char *line, proto_cmd *out);

#endif /* PANEL_PROTOCOL_H */
