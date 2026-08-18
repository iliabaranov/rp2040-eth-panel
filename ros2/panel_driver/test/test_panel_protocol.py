"""Unit tests for the pure panel_protocol helpers (no ROS graph required).

Run standalone (a sourced ROS env injects pytest plugins that break collection):
    PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest test/
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from panel_driver.panel_protocol import (  # noqa: E402
    color_rgba_to_bytes, fmt_hello_cmd, fmt_lamp_cmd, fmt_ring_cmd,
    parse_event,
)


# ---- parse_event: btn ----

def test_parse_btn_down():
    ev = parse_event('{"t":"btn","id":1,"e":"down","ms":123456}')
    assert ev == {"t": "btn", "id": 1, "e": "down", "ms": 123456}


def test_parse_btn_up():
    ev = parse_event('{"t":"btn","id":2,"e":"up","ms":124102}')
    assert ev == {"t": "btn", "id": 2, "e": "up", "ms": 124102}


def test_parse_btn_missing_fields_rejected():
    assert parse_event('{"t":"btn","id":1}') is None          # no edge
    assert parse_event('{"t":"btn","e":"down"}') is None      # no id
    assert parse_event('{"t":"btn","id":"1","e":"down"}') is None  # id not int
    assert parse_event('{"t":"btn","id":1,"e":"sideways"}') is None


# ---- parse_event: hello ----

def test_parse_hello_with_pressed_array():
    ev = parse_event(
        '{"t":"hello","fw":"1.0.0","buttons":2,"rings":[16,16],'
        '"pressed":[false,true],"ip":"10.74.29.12"}'
    )
    assert ev == {
        "t": "hello",
        "fw": "1.0.0",
        "buttons": 2,
        "rings": [16, 16],
        "pressed": [False, True],
        "ip": "10.74.29.12",
    }


def test_parse_hello_missing_pressed_normalizes_to_empty():
    ev = parse_event('{"t":"hello","fw":"1.0.0"}')
    assert ev is not None
    assert ev["t"] == "hello"
    assert ev["pressed"] == []
    assert ev["rings"] == []
    assert ev["ip"] is None


# ---- parse_event: ack / err passthrough ----

def test_parse_ack_passthrough():
    assert parse_event('{"t":"ack","cmd":"ring"}') == {"t": "ack", "cmd": "ring"}


def test_parse_err_passthrough():
    assert parse_event('{"t":"err","msg":"bad ring id"}') == \
        {"t": "err", "msg": "bad ring id"}


# ---- parse_event: garbage ----

def test_parse_rejects_garbage():
    assert parse_event("") is None
    assert parse_event("   ") is None
    assert parse_event("not json") is None
    assert parse_event("[1,2,3]") is None            # JSON but not an object
    assert parse_event('{"no_t":true}') is None
    assert parse_event('{"t":"bogus"}') is None
    assert parse_event(None) is None


# ---- fmt_ring_cmd ----

def test_fmt_ring_cmd_exact_json():
    assert fmt_ring_cmd(1, 255, 64, 0, 128) == \
        '{"cmd":"ring","id":1,"r":255,"g":64,"b":0,"brightness":128}\n'


def test_fmt_ring_cmd_clamps():
    assert fmt_ring_cmd(2, -5, 300, 0, 999) == \
        '{"cmd":"ring","id":2,"r":0,"g":255,"b":0,"brightness":255}\n'


def test_fmt_ring_cmd_ends_with_newline():
    assert fmt_ring_cmd(1, 0, 0, 0, 0).endswith("}\n")


# ---- fmt_lamp_cmd ----

def test_fmt_lamp_cmd():
    assert fmt_lamp_cmd(True) == '{"cmd":"lamp","on":true}\n'
    assert fmt_lamp_cmd(False) == '{"cmd":"lamp","on":false}\n'


# ---- fmt_hello_cmd ----

def test_fmt_hello_cmd():
    assert fmt_hello_cmd() == '{"cmd":"hello"}\n'


# ---- color_rgba_to_bytes ----

def test_color_conversion_rounding():
    assert color_rgba_to_bytes(1.0, 0.0, 0.25, 0.5) == (255, 0, 64, 128)
    assert color_rgba_to_bytes(0.0, 0.0, 0.0, 1.0) == (0, 0, 0, 255)


def test_color_conversion_alpha_zero_is_off():
    # ColorRGBA defaults a to 0.0 -> brightness 0 (ring OFF).
    assert color_rgba_to_bytes(1.0, 1.0, 1.0, 0.0) == (255, 255, 255, 0)


def test_color_conversion_clamps_out_of_range():
    assert color_rgba_to_bytes(-1.0, 2.0, 0.5, 1.5) == (0, 255, 128, 255)
