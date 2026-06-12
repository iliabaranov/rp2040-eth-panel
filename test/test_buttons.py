"""Button debounce tests (pure logic, synthetic millisecond clock, no hardware).

Debounce model under test (buttons.c): a raw level must hold a value DIFFERENT
from the committed state for >= debounce_ms at update() time before the edge is
reported — exactly once. The first update only seeds state (no phantom edges).
"""
import coredef

DEBOUNCE = 30  # DEBOUNCE_MS_DEFAULT in src/config.h

UP = (0, 0)


def test_first_update_seeds_without_events(lib):
    """A button held at the very first update emits NO edge event, but its
    state is immediately readable via the pressed query (the host learns it
    from the hello line instead)."""
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        assert bt.update((1, 0), 0) == []
        assert bt.pressed(0) is True
        assert bt.pressed(1) is False
        # Still no retroactive edge while it stays held.
        assert bt.update((1, 0), 1000) == []
        assert bt.pressed(0) is True
    finally:
        bt.free()


def test_press_edge_at_debounce_boundary(lib):
    """The down edge is reported only once the new level has held >= 30 ms at
    update() time: nothing at 29 ms held, the edge exactly at 30 ms held."""
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        assert bt.update(UP, 0) == []                 # seed: both released
        assert bt.update((1, 0), 10) == []            # raw change starts the window
        assert bt.update((1, 0), 39) == []            # held 29 ms < 30 -> nothing
        assert bt.update((1, 0), 40) == [(1, True)]   # held 30 ms >= 30 -> DOWN
        assert bt.pressed(0) is True
        # The edge is reported exactly once.
        assert bt.update((1, 0), 41) == []
        assert bt.update((1, 0), 500) == []
    finally:
        bt.free()


def test_press_bounce_shorter_than_debounce_ignored(lib):
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        assert bt.update(UP, 0) == []
        assert bt.update((1, 0), 5) == []     # contact closes...
        assert bt.update(UP, 20) == []        # ...and bounces open after 15 ms
        assert bt.update(UP, 200) == []       # never reaches 30 ms held -> no event
        assert bt.pressed(0) is False
    finally:
        bt.free()


def test_release_edge_is_debounced_too(lib):
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        assert bt.update(UP, 0) == []
        bt.update((1, 0), 10)
        assert bt.update((1, 0), 40) == [(1, True)]
        assert bt.update(UP, 50) == []                 # release starts its window
        assert bt.update(UP, 79) == []                 # held 29 ms -> nothing
        assert bt.update(UP, 80) == [(1, False)]       # held 30 ms -> UP
        assert bt.pressed(0) is False
    finally:
        bt.free()


def test_release_bounce_back_to_pressed_ignored(lib):
    """A brief open-contact flicker while pressed must not emit an UP edge."""
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        bt.update(UP, 0)
        bt.update((1, 0), 10)
        assert bt.update((1, 0), 40) == [(1, True)]
        assert bt.update(UP, 50) == []          # opens...
        assert bt.update((1, 0), 60) == []      # ...bounces closed after 10 ms
        assert bt.update((1, 0), 300) == []     # stable pressed again -> no edges
        assert bt.pressed(0) is True
    finally:
        bt.free()


def test_both_buttons_independent(lib):
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        bt.update(UP, 0)
        bt.update((1, 0), 10)                          # btn 1 down at t=10
        bt.update((1, 1), 20)                          # btn 2 down at t=20
        assert bt.update((1, 1), 40) == [(1, True)]    # only btn 1 has 30 ms held
        assert bt.update((1, 1), 50) == [(2, True)]    # btn 2 follows at its own time
        assert bt.pressed(0) is True and bt.pressed(1) is True
        # Releasing btn 1 doesn't disturb btn 2.
        bt.update((0, 1), 60)
        assert bt.update((0, 1), 90) == [(1, False)]
        assert bt.pressed(1) is True
    finally:
        bt.free()


def test_set_debounce_applies_at_runtime(lib):
    """config {"debounce_ms":N} path: a runtime change governs later samples."""
    bt = coredef.Buttons(lib, DEBOUNCE)
    try:
        bt.update(UP, 0)
        bt.set_debounce(100)
        bt.update((1, 0), 10)
        assert bt.update((1, 0), 40) == []              # 30 ms held: old window over,
        assert bt.update((1, 0), 109) == []             # new 100 ms window not yet
        assert bt.update((1, 0), 110) == [(1, True)]    # held 100 ms -> DOWN
        # And shortening it applies to the release.
        bt.set_debounce(5)
        bt.update(UP, 200)
        assert bt.update(UP, 205) == [(1, False)]       # held 5 ms suffices now
    finally:
        bt.free()
