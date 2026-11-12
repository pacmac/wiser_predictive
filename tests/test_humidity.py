"""humidity.py: the estimated dampness of an external wall's inside surface, against known physics and known answers."""
import importlib.util
import pathlib
import sys

_root = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("wiser_predictive_humidity", _root / "custom_components" / "wiser_predictive" / "humidity.py")
h = importlib.util.module_from_spec(_spec)
sys.modules["wiser_predictive_humidity"] = h
_spec.loader.exec_module(h)

H = 3600.0


def test_saturation_pressure_and_dew_point_match_published_table_values():
    # The Magnus form is within 0.3% of the tables over this range (12.260 against 12.28 at 10 C, 23.326 against 23.39 at 20 C), so 0.4%.
    assert abs(h.sat_pressure(10) - 12.28) < 12.28 * 0.004   # psychrometric tables: 12.28 hPa at 10 C
    assert abs(h.sat_pressure(20) - 23.39) < 23.39 * 0.004   # 23.39 hPa at 20 C
    assert abs(h.dew_point(20, 50) - 9.3) < 0.1     # 20 C at 50% has a dew point of 9.3 C
    assert abs(h.dew_point(7.0, 100) - 7.0) < 1e-6  # saturated air: dew point is the temperature
    assert h.dew_point(10, 0) is None and h.dew_point(10, None) is None


def test_floor_is_where_the_wall_just_meets_the_limit():
    for k in (1.0, 1.14):
        for f in (0.73, 0.9):
            for _, limit, _ in h.LIMITS:
                e_out = 9.88  # hPa, the 10-11 Nov forecast's mean vapour pressure
                t = h.floor(7.9, e_out, limit, k, f)
                if t == 7.9:  # the limit is not binding: even a room at the outside temperature is within it
                    assert h.activity(7.9, 7.9, e_out, k, f) <= limit
                    continue
                assert abs(h.activity(t, 7.9, e_out, k, f) - limit) < 1e-3
                assert h.activity(t + 0.5, 7.9, e_out, k, f) < limit  # warmer is drier


def test_floor_reproduces_the_spec_figures():
    # docs/SPEC.md, STAGE 3 DESIGN: mean outdoor 7.9 C and 9.88 hPa, f 0.73, monthly 0.75: 12.3 C at k=1.00 and 15.0 C at k=1.14
    assert abs(h.floor(7.9, 9.88, 0.75, 1.00, 0.73) - 12.3) < 0.1
    assert abs(h.floor(7.9, 9.88, 0.75, 1.14, 0.73) - 15.0) < 0.1
    assert abs(h.floor(7.9, 9.88, 0.85, 1.14, 0.73) - 12.4) < 0.1  # weekly
    # a surface as warm as the air (f = 1) and k = 1 reduces to plain room humidity: the floor is where the AIR meets the limit
    t = h.floor(7.9, 9.88, 0.75, 1.0, 1.0)
    assert abs(h.sat_pressure(t) * 0.75 - 9.88) < 0.01


def test_floor_is_never_below_outside_and_is_capped_when_nothing_works():
    assert h.floor(8.0, 0.5, 0.75, 1.14, 0.73) == 8.0           # very dry air: no heat needed, the room can sit at the outside temperature
    assert h.floor(8.0, 500.0, 0.75, 1.14, 0.73) == h.HOTTEST_C  # impossible vapour pressure: the ceiling, not a made-up answer


def test_a_better_wall_is_drier_and_a_damper_house_is_wetter():
    e = 9.88
    assert h.activity(12.5, 7.9, e, 1.14, 0.9) < h.activity(12.5, 7.9, e, 1.14, 0.73)
    assert h.activity(12.5, 7.9, e, 1.14, 0.73) > h.activity(12.5, 7.9, e, 1.0, 0.73)
    assert h.room_rh(12.5, e, 1.0) < h.room_rh(12.5, e, 1.14)


def test_defaults_are_the_derived_values():
    assert h.DEFAULT_WALL_FACTOR == 0.73 and abs((1 - 0.13 * 2.1) - h.DEFAULT_WALL_FACTOR) < 0.005
    assert h.DEFAULT_INDOOR_DAMP == 1.14
    assert [(n, l, hrs) for n, l, hrs in h.LIMITS] == [("day", 0.95, 24), ("week", 0.85, 168), ("month", 0.75, 720)]


def test_hourly_weather_one_row_per_hour_carries_forward_and_leaves_a_real_gap():
    rows = [(10 * H + 100, 5.0, 80.0), (11 * H + 100, 6.0, 82.0), (20 * H, 9.0, 70.0)]
    out = h.hourly_weather(rows)
    times = [t for t, _, _ in out]
    assert times[0] == 11 * H  # hour 10 starts 100 s before the first row: no value yet
    assert (11 * H, 5.0, 80.0) in out and (12 * H, 6.0, 82.0) in out and (13 * H, 6.0, 82.0) in out and (14 * H, 6.0, 82.0) in out
    assert 15 * H not in times and 19 * H not in times  # more than 3 h since the last row: a gap, not a value
    assert (20 * H, 9.0, 70.0) in out
    assert h.hourly_weather([]) == []
    # `until` carries the last row forward to now (the panel), within the same gap limit; without it the hours stop at the last row
    assert h.hourly_weather([(5 * H, 7.0, 90.0)])[-1][0] == 5 * H
    assert [t for t, _, _ in h.hourly_weather([(5 * H, 7.0, 90.0)], until=7.5 * H)] == [5 * H, 6 * H, 7 * H]
    assert [t for t, _, _ in h.hourly_weather([(5 * H, 7.0, 90.0)], until=12 * H)] == [5 * H, 6 * H, 7 * H, 8 * H]  # then the 3 h limit


def test_hourly_from_states_skips_rows_without_both_values():
    states = [(0.0, {"temperature": 5, "humidity": 80}), (H, {"temperature": 6}), (2 * H, {"temperature": 7, "humidity": "n/a"}), (3 * H, {"temperature": 8, "humidity": 90})]
    out = h.hourly_from_states(states)
    assert (0.0, 5.0, 80.0) in out and (3 * H, 8.0, 90.0) in out
    assert all(row[2] in (80.0, 90.0) for row in out)


def test_forecast_rows_and_join_put_the_forecast_after_the_last_hour_that_happened():
    rows = [{"datetime": "1970-01-01T05:00:00+00:00", "temperature": 8, "humidity": 90},
            {"datetime": "1970-01-01T06:00:00+00:00", "temperature": 7, "humidity": 91},
            {"datetime": "1970-01-01T07:00:00+00:00", "temperature": 6},       # no humidity: left out
            {"datetime": "1970-01-01T08:00:00+00:00", "temperature": 5, "humidity": 95}]
    fc = h.forecast_rows(rows)
    assert fc == [(5 * H, 8.0, 90.0), (6 * H, 7.0, 91.0), (8 * H, 5.0, 95.0)]
    actual = [(4 * H, 9.0, 88.0), (5 * H, 8.5, 89.0)]
    assert h.join_weather(actual, fc) == [(4 * H, 9.0, 88.0), (5 * H, 8.5, 89.0), (6 * H, 7.0, 91.0), (8 * H, 5.0, 95.0)]
    assert h.join_weather([], fc) == fc


def test_shifted_keeps_the_water_so_colder_air_is_more_humid():
    (t, temp, rh), = h.shifted([(0.0, 8.0, 80.0)], -2.0)  # 8 C at 80% is 8.57 hPa; 6 C saturates at 9.35 hPa, so 91.6%
    assert temp == 6.0 and 91.0 < rh < 92.0
    assert abs(h.vapour_pressure(temp, rh) - h.vapour_pressure(8.0, 80.0)) < 1e-9
    assert abs(h.dew_point(temp, rh) - h.dew_point(8.0, 80.0)) < 1e-6  # the same air, so the same dew point
    (_, _, rh2), = h.shifted([(0.0, 8.0, 99.0)], -8.0)
    assert rh2 == 100.0  # cannot exceed saturation


def _weather(now, past_h=48, ahead_h=48, temp=7.9, rh=88.0):
    return [(now + i * H, temp, rh) for i in range(-past_h, ahead_h + 1)]


def test_chart_block_uses_the_prediction_for_the_future_and_leaves_it_out_without_one():
    now = 100 * H
    reading = [(now - i * H, 13.0) for i in range(50, -1, -1)]
    w = _weather(now)
    without = h.chart_block(reading, w, now)
    assert all(t <= now for t, _ in without["activity"])  # nothing invented for the hours ahead
    curve = [[now, 13.0], [now + 24 * H, 11.0], [now + 48 * H, 11.0]]
    withc = h.chart_block(reading, w, now, curve=curve)
    ahead = [a for t, a in withc["activity"] if t > now]
    assert ahead and ahead[-1] > ahead[0]  # the room cools in the prediction, so the wall gets damper
    assert withc["limits"] == {"day": 0.95, "week": 0.85, "month": 0.75}


def test_chart_block_now_means_and_floors():
    now = 100 * H
    reading = [(now - i * H, 13.0) for i in range(50, -1, -1)]
    b = h.chart_block(reading, _weather(now), now)
    e = h.vapour_pressure(7.9, 88.0)
    assert abs(b["now"]["activity"] - h.activity(13.0, 7.9, e, h.DEFAULT_INDOOR_DAMP, h.DEFAULT_WALL_FACTOR)) < 1e-3
    assert abs(b["now"]["dew"] - h.dew_point(7.9, 88.0)) < 0.01
    assert b["means"]["day"]["hours"] == 24 and b["means"]["week"]["hours"] == 49  # the history given is 49 hourly values: the week figure rests on fewer than 168
    assert b["means"]["week"]["of"] == 168 and b["means"]["month"]["of"] == 720
    assert abs(b["floor"]["month"]["temp"] - h.floor(7.9, e, 0.75, h.DEFAULT_INDOOR_DAMP, h.DEFAULT_WALL_FACTOR)) < 0.02
    assert b["floor"]["day"]["temp"] < b["floor"]["week"]["temp"] < b["floor"]["month"]["temp"]  # the looser the limit's period, the stricter its limit
    assert b["floor"]["month"]["hours"] == 48


def test_chart_block_has_no_now_row_when_the_room_has_no_reading():
    now = 100 * H
    b = h.chart_block([], _weather(now), now)
    assert b["now"] is None and b["activity"] == [] and b["means"]["day"]["value"] is None
    assert len(b["dew"]) > 0  # the outdoor dew point does not need the room


def test_moisture_floor_is_the_weekly_floor_for_the_forecasts_mean_weather():
    now = 100 * H
    w = _weather(now)  # 7.9 C at 88% for 48 h before and after
    e = h.vapour_pressure(7.9, 88.0)
    assert abs(h.moisture_floor(w, now) - h.floor(7.9, e, 0.85, h.DEFAULT_INDOOR_DAMP, h.DEFAULT_WALL_FACTOR)) < 0.01
    assert h.moisture_floor(w, now, limit_name="month") > h.moisture_floor(w, now) > h.moisture_floor(w, now, limit_name="day")
    assert h.moisture_floor([w_ for w_ in w if w_[0] <= now], now) is None  # no forecast, no floor
    assert h.moisture_floor([], now) is None
    colder_drier = [(t, 3.0, 70.0) for t, _, _ in w]
    assert h.moisture_floor(colder_drier, now) < h.moisture_floor(w, now)  # cold dry air needs a cooler room to keep the walls dry
