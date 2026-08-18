"""Line-delimited JSON protocol tests (pure logic, no hardware).

Formatter assertions are byte-exact — field order and the trailing newline are
part of the wire contract the host-side consumers parse line-by-line.
"""
import coredef
from coredef import (CMD_NONE, CMD_RING, CMD_LAMP, CMD_CONFIG, CMD_PING,
                     CMD_OTA, CMD_HELLO, CMD_UNKNOWN)


# ---- device -> host formatters ----

def test_fmt_btn_byte_exact(lib):
    rc, s = coredef.fmt_btn(lib, 1, True, 123456)
    assert s == '{"t":"btn","id":1,"e":"down","ms":123456}\n'
    assert rc == len(s)
    rc, s = coredef.fmt_btn(lib, 2, False, 124102)
    assert s == '{"t":"btn","id":2,"e":"up","ms":124102}\n'
    assert rc == len(s)


def test_fmt_hello_byte_exact(lib):
    rc, s = coredef.fmt_hello(lib, "1.0.0", (16, 16), (False, False), "10.74.29.12")
    assert s == ('{"t":"hello","fw":"1.0.0","buttons":2,"rings":[16,16],'
                 '"pressed":[false,false],"ip":"10.74.29.12"}\n')
    assert rc == len(s)
    # Boot-time held button and asymmetric rings must show through.
    _, s = coredef.fmt_hello(lib, "1.1.0", (16, 12), (True, False), "192.168.0.9")
    assert s == ('{"t":"hello","fw":"1.1.0","buttons":2,"rings":[16,12],'
                 '"pressed":[true,false],"ip":"192.168.0.9"}\n')


def test_fmt_ack_err_byte_exact(lib):
    rc, s = coredef.fmt_ack(lib, "ring")
    assert s == '{"t":"ack","cmd":"ring"}\n'
    assert rc == len(s)
    rc, s = coredef.fmt_err(lib, "bad ring id")
    assert s == '{"t":"err","msg":"bad ring id"}\n'
    assert rc == len(s)


def test_fmt_truncation_returns_minus1(lib):
    assert coredef.fmt_btn(lib, 1, True, 123456, bufn=8)[0] == -1
    assert coredef.fmt_hello(lib, "1.0.0", (16, 16), (False, False),
                             "10.74.29.12", bufn=32)[0] == -1
    assert coredef.fmt_ack(lib, "ring", bufn=8)[0] == -1
    assert coredef.fmt_err(lib, "bad ring id", bufn=8)[0] == -1


# ---- host -> device parser ----

def test_parse_ring_full(lib):
    c = coredef.parse_cmd(lib,
        '{"cmd":"ring","id":1,"r":255,"g":64,"b":0,"brightness":128}')
    assert c["found"] is True
    assert c["type"] == CMD_RING
    assert c["id"] == 1
    assert (c["r"], c["g"], c["b"]) == (255, 64, 0)
    assert c["brightness"] == 128


def test_parse_ring_partial_absent_fields_are_minus1(lib):
    c = coredef.parse_cmd(lib, '{"cmd":"ring","id":2,"g":7}')
    assert c["type"] == CMD_RING
    assert c["id"] == 2
    assert c["g"] == 7
    assert c["r"] == -1 and c["b"] == -1 and c["brightness"] == -1
    # Bare ring command: everything absent.
    c = coredef.parse_cmd(lib, '{"cmd":"ring"}')
    assert c["type"] == CMD_RING
    assert (c["id"], c["r"], c["g"], c["b"], c["brightness"]) == (-1,) * 5


def test_parse_lamp_bool_and_numeric_forms(lib):
    assert coredef.parse_cmd(lib, '{"cmd":"lamp","on":true}')["on"] == 1
    assert coredef.parse_cmd(lib, '{"cmd":"lamp","on":false}')["on"] == 0
    assert coredef.parse_cmd(lib, '{"cmd":"lamp","on":1}')["on"] == 1
    assert coredef.parse_cmd(lib, '{"cmd":"lamp","on":0}')["on"] == 0
    c = coredef.parse_cmd(lib, '{"cmd":"lamp"}')
    assert c["type"] == CMD_LAMP
    assert c["on"] == -1                       # absent


def test_parse_config(lib):
    c = coredef.parse_cmd(lib, '{"cmd":"config","debounce_ms":45}')
    assert c["type"] == CMD_CONFIG
    assert c["debounce_ms"] == 45
    assert coredef.parse_cmd(lib, '{"cmd":"config"}')["debounce_ms"] == -1


def test_parse_ping_and_ota(lib):
    assert coredef.parse_cmd(lib, '{"cmd":"ping"}')["type"] == CMD_PING
    assert coredef.parse_cmd(lib, '{"cmd":"ota"}')["type"] == CMD_OTA


def test_parse_hello_request(lib):
    assert coredef.parse_cmd(lib, '{"cmd":"hello"}')["type"] == CMD_HELLO


def test_parse_whitespace_tolerance(lib):
    c = coredef.parse_cmd(lib, '{ "cmd" : "ring" , "id" : 1 , "r" : 9 }')
    assert c["type"] == CMD_RING
    assert c["id"] == 1 and c["r"] == 9
    assert coredef.parse_cmd(lib, '  { "cmd" : "ping" }  ')["type"] == CMD_PING


def test_parse_key_order_tolerance(lib):
    c = coredef.parse_cmd(lib, '{"id":2,"brightness":40,"cmd":"ring","r":3}')
    assert c["type"] == CMD_RING
    assert c["id"] == 2 and c["r"] == 3 and c["brightness"] == 40


def test_parse_missing_cmd_returns_false(lib):
    c = coredef.parse_cmd(lib, '{"nope":1}')
    assert c["found"] is False
    assert c["type"] == CMD_NONE


def test_parse_unknown_verb_is_cmd_unknown(lib):
    c = coredef.parse_cmd(lib, '{"cmd":"frobnicate"}')
    assert c["found"] is True                   # a cmd field WAS present
    assert c["type"] == CMD_UNKNOWN
