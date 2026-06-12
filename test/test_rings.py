"""WS2812 ring state tests: brightness scaling, pixel packing, dirty tracking,
render (pure logic, no hardware)."""
import coredef
from coredef import ORDER_GRB, ORDER_RGB


def _ring(lib, nleds=(16, 16)):
    return coredef.Rings(lib, nleds)


# ---- brightness scaling: (c*brightness+127)/255, round-to-nearest ----

def test_scale_passthrough_and_zero(lib):
    for c in (0, 1, 17, 128, 254, 255):
        assert coredef.scale(lib, c, 255) == c     # 255 = passthrough
        assert coredef.scale(lib, c, 0) == 0       # 0 = fully off
    assert coredef.scale(lib, 0, 128) == 0         # black stays black


def test_scale_half_brightness(lib):
    assert coredef.scale(lib, 255, 128) == 128     # 255*128/255 = 128
    assert coredef.scale(lib, 128, 128) == 64      # 64.25 -> 64
    assert coredef.scale(lib, 200, 128) == 100     # 100.39 -> 100


def test_scale_rounds_to_nearest_at_boundaries(lib):
    # 1*127/255 = 0.498 -> 0, but 1*128/255 = 0.502 -> 1.
    assert coredef.scale(lib, 1, 127) == 0
    assert coredef.scale(lib, 1, 128) == 1
    # 3*212/255 = 2.494 -> 2, but 3*213/255 = 2.506 -> 3.
    assert coredef.scale(lib, 3, 212) == 2
    assert coredef.scale(lib, 3, 213) == 3
    # Spot-check the exact formula across the range.
    for c in (2, 50, 99, 201, 255):
        for b in (1, 64, 127, 200, 254):
            assert coredef.scale(lib, c, b) == (c * b + 127) // 255


# ---- pixel word packing ----

def test_pixel_word_grb_vs_rgb(lib):
    rg = _ring(lib)
    try:
        assert rg.set(0, r=10, g=20, b=30, brightness=255)
        assert rg.pixel_word(0, ORDER_GRB) == (20 << 16) | (10 << 8) | 30
        assert rg.pixel_word(0, ORDER_RGB) == (10 << 16) | (20 << 8) | 30
    finally:
        rg.free()


def test_pixel_word_applies_brightness(lib):
    rg = _ring(lib)
    try:
        assert rg.set(0, r=255, g=100, b=0, brightness=128)
        # scaled: r=128, g=50 ((100*128+127)/255 = 50.6 -> 50... check below), b=0
        sr = coredef.scale(lib, 255, 128)
        sg = coredef.scale(lib, 100, 128)
        assert rg.pixel_word(0, ORDER_GRB) == (sg << 16) | (sr << 8) | 0
    finally:
        rg.free()


def test_init_renders_black(lib):
    rg = _ring(lib)
    try:
        assert rg.pixel_word(0, ORDER_GRB) == 0
        assert rg.pixel_word(1, ORDER_RGB) == 0
    finally:
        rg.free()


# ---- per-ring independence / partial updates ----

def test_per_ring_independence(lib):
    rg = _ring(lib)
    try:
        assert rg.set(0, r=200, g=0, b=0, brightness=255)
        assert rg.pixel_word(1, ORDER_GRB) == 0          # ring 1 untouched
        assert rg.set(1, r=0, g=0, b=99, brightness=255)
        assert rg.pixel_word(0, ORDER_GRB) == 200 << 8   # ring 0 unchanged
        assert rg.pixel_word(1, ORDER_GRB) == 99
    finally:
        rg.free()


def test_partial_update_keeps_current_values(lib):
    rg = _ring(lib)
    try:
        assert rg.set(0, r=100, g=50, b=25, brightness=255)
        before = rg.pixel_word(0, ORDER_GRB)
        # brightness-only change: color channels survive
        assert rg.set(0, brightness=255)                 # same -> no visible change
        assert rg.pixel_word(0, ORDER_GRB) == before
        assert rg.set(0, g=60)                           # g-only change
        assert rg.pixel_word(0, ORDER_GRB) == (60 << 16) | (100 << 8) | 25
        assert rg.set(0, brightness=0)                   # dims, doesn't erase color
        assert rg.pixel_word(0, ORDER_GRB) == 0
        assert rg.set(0, brightness=255)                 # color comes back intact
        assert rg.pixel_word(0, ORDER_GRB) == (60 << 16) | (100 << 8) | 25
    finally:
        rg.free()


# ---- validation ----

def test_out_of_range_rejected_state_unchanged(lib):
    rg = _ring(lib)
    try:
        assert rg.set(0, r=1, g=2, b=3, brightness=255)
        before = rg.pixel_word(0, ORDER_GRB)
        rg.clear_dirty(0)
        assert rg.set(2, r=1) is False                   # bad ring idx
        assert rg.set(-1, r=1) is False
        assert rg.set(0, r=256) is False                 # channel > 255
        assert rg.set(0, g=-2) is False                  # below the -1 sentinel
        assert rg.set(0, brightness=300) is False
        assert rg.pixel_word(0, ORDER_GRB) == before     # state untouched
        assert rg.dirty(0) is False                      # and not marked dirty
    finally:
        rg.free()


# ---- dirty tracking ----

def test_init_marks_both_rings_dirty(lib):
    rg = _ring(lib)
    try:
        assert rg.dirty(0) is True   # first render must push a known dark frame
        assert rg.dirty(1) is True
    finally:
        rg.free()


def test_dirty_only_on_effective_change(lib):
    rg = _ring(lib)
    try:
        rg.clear_dirty(0)
        rg.clear_dirty(1)
        assert rg.set(0, r=5, g=6, b=7) is True
        assert rg.dirty(0) is True                   # state changed
        assert rg.dirty(1) is False                  # other ring untouched
        rg.clear_dirty(0)
        assert rg.set(0, r=5, g=6, b=7) is True      # same color again: accepted...
        assert rg.dirty(0) is False                  # ...but nothing changed
        assert rg.set(0) is True                     # all -1 = no-op
        assert rg.dirty(0) is False
        assert rg.set(0, brightness=10) is True      # an actual change
        assert rg.dirty(0) is True
    finally:
        rg.free()


# ---- render ----

def test_render_fills_n_copies(lib):
    rg = _ring(lib, nleds=(16, 12))
    try:
        assert rg.set(1, r=10, g=20, b=30, brightness=255)
        w = rg.pixel_word(1, ORDER_GRB)
        assert rg.render(1, ORDER_GRB, max_words=12) == [w] * 12
        assert rg.render(1, ORDER_GRB, max_words=64) == [w] * 12  # bigger buf is fine
        assert rg.render(0, ORDER_GRB, max_words=16) == [0] * 16  # ring 0 still black
    finally:
        rg.free()


def test_render_rejects_too_small_buffer_and_bad_idx(lib):
    rg = _ring(lib, nleds=(16, 12))
    try:
        assert rg.render(0, ORDER_GRB, max_words=15) is None
        assert rg.render(1, ORDER_GRB, max_words=11) is None
        assert rg.render(2, ORDER_GRB, max_words=64) is None
        assert rg.render(-1, ORDER_GRB, max_words=64) is None
    finally:
        rg.free()


def test_render_does_not_clear_dirty(lib):
    rg = _ring(lib)
    try:
        assert rg.dirty(0) is True
        rg.render(0, ORDER_GRB)
        assert rg.dirty(0) is True       # the glue clears it after a real push
        rg.clear_dirty(0)
        assert rg.dirty(0) is False
    finally:
        rg.free()
