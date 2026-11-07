"""model.py: time to minimum from a recent window of readings. Points are (minutes, degrees C)."""
import importlib.util
import math
import pathlib
import sys

_p = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "wiser_predictive" / "model.py"
_s = importlib.util.spec_from_file_location("model_fit", _p)
model = importlib.util.module_from_spec(_s)
sys.modules["model_fit"] = model
_s.loader.exec_module(model)


def series(fn, start=0, stop=120, step=5):
    return [(t, fn(t)) for t in range(start, stop + 1, step)]


def test_recent_keeps_only_the_window_ending_now():
    pts = [(0, 1.0), (50, 2.0), (100, 3.0), (150, 4.0)]
    assert model.recent(pts, now=150, window=100) == [(50, 2.0), (100, 3.0), (150, 4.0)]


def test_linear_exact_cooling():
    # 14.0 falling 0.01 C/min; at t=120 it is 12.8, minimum 12.0 -> 80 minutes
    p = model.predict_linear(series(lambda t: 14.0 - 0.01 * t), minimum=12.0)
    assert p.reason == "ok"
    assert abs(p.minutes - 80.0) < 1e-6


def test_linear_on_tenth_degree_steps_is_close():
    p = model.predict_linear(series(lambda t: round(14.0 - 0.01 * t, 1)), minimum=12.0)
    assert p.reason == "ok"
    assert abs(p.minutes - 80.0) < 15.0


def test_short_window_is_unknown_not_a_guess():
    p = model.predict_linear(series(lambda t: 14.0 - 0.01 * t, stop=60), minimum=12.0)
    assert (p.minutes, p.reason) == (None, "short_window")


def test_fewer_points_than_a_line_needs_is_a_short_window():
    assert model.predict_linear([(0, 14.0)], minimum=12.0).reason == "short_window"
    assert model.predict_linear([], minimum=12.0).reason == "short_window"


def test_flat_or_rising_is_not_cooling():
    assert model.predict_linear(series(lambda t: 13.0), minimum=12.0).reason == "not_cooling"
    assert model.predict_linear(series(lambda t: 13.0 + 0.01 * t), minimum=12.0).reason == "not_cooling"


def test_already_at_or_below_minimum_is_zero_minutes():
    p = model.predict_linear(series(lambda t: 12.2 - 0.01 * t), minimum=12.0)  # fitted now = 11.0
    assert (p.minutes, p.reason) == (0.0, "ok")


def test_newton_exact_cooling():
    # outside 5, start 15, k 0.002/min: reaches 12.0 at ln(10/7)/k = 178.3 min; at t=120 -> 58.3 left
    k, to = 0.002, 5.0
    p = model.predict_newton(series(lambda t: to + 10.0 * math.exp(-k * t)), minimum=12.0, outside=to)
    expected = math.log(10.0 / 7.0) / k - 120
    assert p.reason == "ok"
    assert abs(p.minutes - expected) < 0.5


def test_newton_never_reaches_a_minimum_at_or_below_outside():
    pts = series(lambda t: 15.0 - 0.01 * t)
    p = model.predict_newton(pts, minimum=12.0, outside=12.0)
    assert (p.minutes, p.reason) == (None, "no_reach")


def test_newton_reading_at_or_below_outside_is_not_cooling_towards_it():
    p = model.predict_newton(series(lambda t: 10.0), minimum=9.0, outside=11.0)
    assert (p.minutes, p.reason) == (None, "not_cooling")


def test_newton_short_window():
    p = model.predict_newton(series(lambda t: 15.0 - 0.01 * t, stop=60), minimum=12.0, outside=5.0)
    assert (p.minutes, p.reason) == (None, "short_window")
