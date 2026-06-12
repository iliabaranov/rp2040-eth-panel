/*
 * protocol.c — pure line-delimited JSON protocol (see protocol.h).
 *
 * The command set is small and fixed, so parsing uses targeted field extraction
 * rather than a full JSON parser: locate "key", skip ':' and whitespace, read the
 * string / integer / boolean value. Tolerant of surrounding whitespace and key order.
 */
#include "protocol/protocol.h"

#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <stdlib.h>

/* ---- event formatters ---- */
static int finish(int written, size_t n) {
    return (written < 0 || (size_t)written >= n) ? -1 : written;
}

int proto_fmt_btn(char *buf, size_t n, int id, bool pressed, uint32_t ms) {
    return finish(snprintf(buf, n, "{\"t\":\"btn\",\"id\":%d,\"e\":\"%s\",\"ms\":%lu}\n",
                           id, pressed ? "down" : "up", (unsigned long)ms), n);
}
int proto_fmt_hello(char *buf, size_t n, const char *fw, const uint16_t nleds[2],
                    const bool pressed[2], const char *ip) {
    return finish(snprintf(buf, n,
                  "{\"t\":\"hello\",\"fw\":\"%s\",\"buttons\":2,\"rings\":[%u,%u],"
                  "\"pressed\":[%s,%s],\"ip\":\"%s\"}\n",
                  fw, (unsigned)nleds[0], (unsigned)nleds[1],
                  pressed[0] ? "true" : "false", pressed[1] ? "true" : "false", ip), n);
}
int proto_fmt_ack(char *buf, size_t n, const char *cmd) {
    return finish(snprintf(buf, n, "{\"t\":\"ack\",\"cmd\":\"%s\"}\n", cmd), n);
}
int proto_fmt_err(char *buf, size_t n, const char *msg) {
    return finish(snprintf(buf, n, "{\"t\":\"err\",\"msg\":\"%s\"}\n", msg), n);
}

/* ---- minimal field extraction ---- */
static const char *find_key(const char *json, const char *key) {
    char pat[40];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) return NULL;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t') p++;
    if (*p != ':') return NULL;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    return p; /* points at the value */
}

/* Extract a string value into dst (size dstn). Returns true if found. */
static bool get_str(const char *json, const char *key, char *dst, size_t dstn) {
    const char *p = find_key(json, key);
    if (!p || *p != '"') return false;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i + 1 < dstn) dst[i++] = *p++;
    dst[i] = '\0';
    return true;
}

/* Extract an integer value. Returns true if found. */
static bool get_int(const char *json, const char *key, int *out) {
    const char *p = find_key(json, key);
    if (!p) return false;
    if (*p != '-' && !isdigit((unsigned char)*p)) return false;
    *out = (int)strtol(p, NULL, 10);
    return true;
}

/* Extract a boolean (true/false, or 1/0 for convenience) into 1/0. */
static bool get_bool(const char *json, const char *key, int *out) {
    const char *p = find_key(json, key);
    if (!p) return false;
    if (strncmp(p, "true", 4) == 0)  { *out = 1; return true; }
    if (strncmp(p, "false", 5) == 0) { *out = 0; return true; }
    if (*p == '1' && !isdigit((unsigned char)p[1])) { *out = 1; return true; }
    if (*p == '0' && !isdigit((unsigned char)p[1])) { *out = 0; return true; }
    return false;
}

bool proto_parse(const char *line, proto_cmd *out) {
    out->type = CMD_NONE;
    out->id = -1;
    out->r = out->g = out->b = -1;
    out->brightness = -1;
    out->on = -1;
    out->debounce_ms = -1;

    char cmd[16];
    if (!get_str(line, "cmd", cmd, sizeof(cmd))) {
        return false;
    }

    if (strcmp(cmd, "ring") == 0) {
        out->type = CMD_RING;
        get_int(line, "id", &out->id);
        get_int(line, "r", &out->r);
        get_int(line, "g", &out->g);
        get_int(line, "b", &out->b);
        get_int(line, "brightness", &out->brightness);
    } else if (strcmp(cmd, "lamp") == 0) {
        out->type = CMD_LAMP;
        get_bool(line, "on", &out->on);
    } else if (strcmp(cmd, "config") == 0) {
        out->type = CMD_CONFIG;
        get_int(line, "debounce_ms", &out->debounce_ms);
    } else if (strcmp(cmd, "ping") == 0) {
        out->type = CMD_PING;
    } else if (strcmp(cmd, "ota") == 0) {
        out->type = CMD_OTA;
    } else {
        out->type = CMD_UNKNOWN;
    }
    return true;
}
