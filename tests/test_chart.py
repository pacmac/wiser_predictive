"""chart.py: the arithmetic behind the chart (rates, holds, spans), on synthetic series with known answers."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parent.parent / "chart.py"
_s = importlib.util.spec_from_file_location("chart", _p)
chart = importlib.util.module_from_spec(_s)
_s.loader.exec_module(chart)

HOUR = 3600
GRID = chart.GRID


def test_a_steady_fall_of_half_a_degree_an_hour_reads_minus_half():
    grid = [k * GRID for k in range(30)]
    values = [20.0 - 0.5 * g / HOUR for g in grid]
    out = chart.rates(grid, values)
    assert out and all(abs(v + 0.5) < 1e-6 for _, v in out)


def test_a_flat_series_has_zero_rate_and_too_few_points_has_none():
    grid = [k * GRID for k in range(10)]
    assert all(v == 0 for _, v in chart.rates(grid, [18.0] * 10))
    assert [g for g, _ in chart.rates(grid, [18.0, 18.0] + [None] * 8)] == []  # fewer than 3 points in the window


def test_the_rate_uses_only_the_trailing_window():
    # flat for 3 h then rising 1 C/h: after more than a window of rise the rate is 1, not an average with the flat part
    grid = [k * GRID for k in range(40)]
    values = [15.0 if g <= 3 * HOUR else 15.0 + (g - 3 * HOUR) / HOUR for g in grid]
    last = chart.rates(grid, values)[-1][1]
    assert abs(last - 1.0) < 1e-6


def test_hold_repeats_the_last_reading_until_the_next():
    pts = [(10, 1.0), (30, 2.0)]
    assert chart.hold(pts, [5, 10, 20, 30, 99]) == [None, 1.0, 1.0, 2.0, 2.0]


def test_interpolate_draws_a_straight_line_between_hourly_points_and_nothing_outside():
    pts = [(0, 10.0), (HOUR, 12.0)]
    assert chart.interpolate(pts, [-1, 0, HOUR // 2, HOUR, HOUR + 1]) == [None, 10.0, 11.0, 12.0, None]


def test_spans_are_the_periods_a_flag_was_true():
    pts = [(0, False), (10, True), (20, True), (30, False), (40, True), (50, True)]
    assert chart.spans(pts) == [(10, 30), (40, 50)]


def test_attribute_rows_come_back_in_time_order():
    rows = [[200.0 * 1000, 1.0], [100.0 * 1000, 2.0], [300.0 * 1000, None]]
    assert chart.column(rows, 1) == [(100.0, 2.0), (200.0, 1.0)]
