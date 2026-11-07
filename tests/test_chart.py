"""series.py (what the panel draws) and chart.py's loading, on synthetic data with known answers."""
import importlib.util
import pathlib
import sys

_root = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(_root / "custom_components" / "wiser_predictive"))  # series.py imports thermal and model as plain modules
series = _load("wiser_predictive_series", _root / "custom_components" / "wiser_predictive" / "series.py")
chart = _load("chart_tool", _root / "chart.py")


def test_spans_are_the_periods_a_flag_was_true_and_an_open_one_ends_at_the_last_point():
    pts = [(0, False), (10, True), (20, True), (30, False), (40, True), (50, True)]
    assert series.spans(pts) == [(10, 30), (40, 50)]
    assert series.spans([]) == []


def test_build_sorts_rows_drops_missing_readings_and_keeps_only_the_forecast_from_an_hour_before_now():
    climate = [
        (200.0, {"current_temperature": 13.0, "is_heating": True, "is_boosted": False}),
        (100.0, {"current_temperature": 12.0, "is_heating": False, "is_boosted": False}),
        (300.0, {"current_temperature": None, "is_heating": False, "is_boosted": False}),
    ]
    out = series.build("Lounge", climate, [(150.0, 6.0)], [(10.0, 1.0), (4000.0, 7.0), (9000.0, 8.0)], now=4000.0, built="t")
    assert out["reading"] == [[100, 12.0], [200, 13.0]]
    assert out["heating"] == [[200, 300]]  # heating from 200 until the next row at 300
    assert out["boost"] == []
    assert out["forecast"] == [[4000, 7.0], [9000, 8.0]]  # the 10 s point is long before now
    assert out["end"] == 4000 + 24 * 3600 and out["name"] == "Lounge" and out["notes"] == []


def test_chart_tool_turns_saved_rows_into_attribute_dicts_in_seconds():
    rows = [[2000.0, 12.5, 12.5, None, 0, False, False, False, False, 12.5]]
    (t, attrs), = chart.climate_rows(rows)
    assert t == 2.0 and attrs["current_temperature"] == 12.5 and attrs["is_heating"] is False
