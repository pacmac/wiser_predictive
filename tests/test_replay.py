"""replay.py: finding the times a room touched its minimum, and measuring boost heat-up. Rows are [ms, temp, minimum, boosted]."""
import importlib.util
import pathlib
import sys

_p = pathlib.Path(__file__).resolve().parent.parent / "replay.py"
_s = importlib.util.spec_from_file_location("replay", _p)
replay = importlib.util.module_from_spec(_s)
sys.modules["replay"] = replay
_s.loader.exec_module(replay)

MIN = 60_000  # one minute in ms


def rows(*spec):
    return [[i * 10 * MIN, temp, minimum, boosted] for i, (temp, minimum, boosted) in enumerate(spec)]


def test_a_touch_is_the_first_reading_at_or_below_the_minimum():
    r = rows((13.0, 12.5, False), (12.6, 12.5, False), (12.5, 12.5, False), (12.4, 12.5, False))
    assert replay.touches(r) == [20.0]  # minutes, row 2


def test_staying_below_is_one_touch_and_a_new_touch_needs_a_return_above():
    r = rows((12.6, 12.5, False), (12.5, 12.5, False), (12.4, 12.5, False), (12.7, 12.5, False), (12.5, 12.5, False))
    assert replay.touches(r) == [10.0, 40.0]


def test_a_one_step_flicker_does_not_re_arm_a_touch():
    # the sensor steps 0.1 C: 12.5 -> 12.6 -> 12.5 is the same touch; it must rise 0.2 above the minimum first
    r = rows((12.6, 12.5, False), (12.5, 12.5, False), (12.6, 12.5, False), (12.5, 12.5, False),
             (12.7, 12.5, False), (12.5, 12.5, False))
    assert replay.touches(r) == [10.0, 50.0]


def test_resample_holds_the_last_reading_between_changes():
    # change-only history: 13.0 at minute 0, 12.9 at minute 60. Sampled every 5 minutes up to minute 120.
    r = [[0, 13.0, 12.5, False], [60 * MIN, 12.9, 12.5, False]]
    pts = replay.resample(r, start=0, now=120, step=5)
    assert pts[0] == (0, 13.0) and pts[-1] == (120, 12.9)
    assert pts[11] == (55, 13.0) and pts[12] == (60, 12.9)
    assert len(pts) == 25


def test_resample_before_the_first_reading_is_empty():
    assert replay.resample([[100 * MIN, 13.0, 12.5, False]], start=0, now=60, step=5) == []


def test_a_level_above_the_minimum_can_be_crossed_instead():
    r = rows((13.0, 12.5, False), (12.9, 12.5, False), (12.7, 12.5, False), (12.5, 12.5, False))
    assert replay.touches(r, offset=0.2) == [20.0]  # first reading at or below minimum + 0.2
    assert replay.touches(r) == [30.0]


def test_raising_the_target_is_not_a_touch():
    r = rows((12.6, 12.5, False), (12.6, 13.5, False))
    assert replay.touches(r) == []


def test_boosted_rows_are_not_touches():
    r = rows((12.6, 12.5, False), (12.4, 12.5, True))
    assert replay.touches(r) == []


def test_heatup_is_minutes_from_boost_start_until_the_reading_is_0_3_higher():
    r = rows((12.5, 12.5, False), (12.5, 15.5, True), (12.6, 15.5, True), (12.8, 15.5, True), (13.0, 15.5, True))
    assert replay.heatups(r) == [20.0]  # boost starts row 1 (10 min), reading reaches 12.8 at row 3 (30 min)


def test_heatup_never_reached_inside_the_boost_is_skipped():
    r = rows((12.5, 12.5, False), (12.5, 15.5, True), (12.6, 15.5, True), (12.5, 12.5, False))
    assert replay.heatups(r) == []
