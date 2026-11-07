"""thermal.py on synthetic rooms with known cooling constants: does the fit find them, and refuse when it cannot?"""
import importlib.util
import math
import pathlib
import sys

_p = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "wiser_predictive" / "thermal.py"
_s = importlib.util.spec_from_file_location("wiser_predictive_thermal", _p)
th = importlib.util.module_from_spec(_s)
sys.modules["wiser_predictive_thermal"] = th
_s.loader.exec_module(th)

TAU, C2 = 20.0, 0.03  # hours; the outside pulls with 0.03 C/h per degree
C1 = -1 / TAU
C0 = 0.25             # gains, C/h


def room(hours, t0=19.0, outside=lambda h: 8.0 + 3.0 * math.sin(2 * math.pi * h / 24), heating=lambda h: False):
    """A room that follows the model exactly, on the model's grid."""
    steps = int(hours * 3600 / th.STEP)
    temps, heat, outs, t = [], [], [], t0
    for k in range(steps):
        h = k * th.STEP / 3600
        o = outside(h)
        temps.append(t); heat.append(heating(h)); outs.append(o)
        t += th.STEP / 3600 * (C0 + C1 * t + C2 * o) + (0.5 * th.STEP / 3600 if heating(h) else 0)
    return temps, heat, outs


def test_the_fit_recovers_the_cooling_constant_and_the_outside_coupling():
    p = th.fit(th.cooling_samples(*room(96)))
    assert p is not None
    assert abs(p.tau_h - TAU) < 1.0 and abs(p.c2 - C2) < 0.005 and abs(p.c0 - C0) < 0.05
    assert abs(p.equilibrium(8.0) - (-(C0 + C2 * 8.0) / C1)) < 0.3


def test_samples_ignore_heating_and_the_hour_after_it():
    temps, heat, outs = room(48, heating=lambda h: 10 <= h < 11)  # steps 60..65 of 288 are heating
    samples = th.cooling_samples(temps, heat, outs)
    # a window of 6 steps may start at 0..53 (it ends before the heating) and from 65 + SETTLE = 71 to the last (281)
    assert len(samples) == 54 + (281 - 71 + 1)


def test_too_little_free_cooling_gives_no_model_rather_than_a_guess():
    assert th.fit(th.cooling_samples(*room(12))) is None  # 12 h of data: fewer than the day it needs


def test_a_flat_room_is_not_a_cooling_curve():
    n = 400
    assert th.fit(th.cooling_samples([15.0] * n, [False] * n, [8.0 + (i % 7) for i in range(n)])) is None


def test_the_simulation_reproduces_the_room_and_finds_when_it_reaches_the_minimum():
    temps, heat, outs = room(96)
    p = th.fit(th.cooling_samples(temps, heat, outs))
    path = th.simulate(p, temps[200], outs[201:201 + 6 * 12])  # 12 h on
    assert abs(path[-1] - temps[200 + 6 * 12]) < 0.1
    assert th.steps_to_reach(path, path[-1] + 0.001) is not None
    assert th.steps_to_reach(path, -50.0) is None


def test_a_missing_outside_reading_drops_the_window_instead_of_counting_it_as_zero():
    temps, heat, outs = room(48)
    outs = list(outs)
    outs[30] = None
    clean = th.cooling_samples(temps, heat, room(48)[2])
    gap = th.cooling_samples(temps, heat, outs)
    assert len(gap) < len(clean)


# --- the heating response and the plan ----------------------------------------------------------------------------------

TMAX, TAU_MIN = 19.0, 80.0


def rows_with_runs(minutes_list, gap_h=30.0, t0=12.6):
    """A room history: heat runs (demand 100%) of the given lengths, each starting gap_h after the last, settling at the heating
    curve; between runs the room just sits at the settled temperature (the fit only needs before/settled readings)."""
    rows, t, now_t = [], t0, 0.0
    rows.append((now_t, {"current_temperature": t, "is_heating": False, "percentage_demand": 0}))
    for m in minutes_list:
        now_t += gap_h * 3600
        rows.append((now_t - 3600, {"current_temperature": t0, "is_heating": False, "percentage_demand": 0}))  # cooled back down
        rows.append((now_t, {"current_temperature": t0, "is_heating": True, "percentage_demand": 100}))
        after = t0 + (TMAX - t0) * (1 - math.exp(-m / TAU_MIN))
        rows.append((now_t + m * 60, {"current_temperature": after, "is_heating": False, "percentage_demand": 0}))
        rows.append((now_t + m * 60 + 2 * th.SETTLED_S, {"current_temperature": after, "is_heating": False, "percentage_demand": 0}))
    return rows


def test_runs_are_found_with_their_full_demand_minutes_and_settled_lift():
    found = th.runs(rows_with_runs([15, 15, 40]))
    assert [round(r["minutes"]) for r in found] == [15, 15, 40]
    assert all(abs(r["before"] - 12.6) < 1e-9 for r in found)
    assert abs(found[0]["settled"] - (12.6 + (TMAX - 12.6) * (1 - math.exp(-15 / TAU_MIN)))) < 1e-9


def test_the_heating_fit_recovers_the_curve_from_runs_of_different_lengths():
    h = th.fit_heating(th.runs(rows_with_runs([10, 15, 15, 20, 40, 90, 150])))
    assert h is not None and abs(h.tmax - TMAX) < 0.4 and abs(h.tau_min - TAU_MIN) < 8 and h.rms < 0.05


def test_too_few_runs_gives_no_heating_model():
    assert th.fit_heating(th.runs(rows_with_runs([15, 15, 15]))) is None


def planned_room():
    temps, heat, outs = room(96)
    p = th.fit(th.cooling_samples(temps, heat, outs))
    h = th.Heating(TMAX, TAU_MIN, 8, 0.0)
    return p, h, temps[-1], outs


def test_the_plan_calls_as_late_as_is_safe_and_holds_the_minimum_to_the_end():
    p, h, t_now, _ = planned_room()
    now, forecast = 1_000_000.0, [(1_000_000.0 + k * 3600, 2.0) for k in range(1, 49)]  # a cold spell: 2 C for 2 days
    minimum = t_now - 0.5
    plan = th.plan(p, h, now, t_now, minimum, forecast, 2.0, horizon_h=48)
    assert plan["runs"], "a room that will fall below its minimum needs a run"
    first = plan["runs"][0]
    free = th.predict(p, now, t_now, minimum, forecast, 2.0, 48)
    assert first["call_by"] == free["call_by"]  # the same latest-safe moment the prediction gives
    assert first["minutes"] % th.RUN_STEP_MIN == 0 and first["lifts_to"] > minimum
    assert min(v for _, v in plan["curve"]) >= minimum - 0.15  # never below it, to within the 30-minute sampling


def test_no_run_is_planned_for_a_room_that_stays_above_its_minimum():
    p, h, t_now, _ = planned_room()
    now = 1_000_000.0
    forecast = [(now + k * 3600, 30.0) for k in range(1, 25)]  # warm: it will not cool to the minimum
    assert th.plan(p, h, now, t_now, 5.0, forecast, 30.0)["runs"] == []


def test_the_prediction_runs_as_far_as_the_forecast_goes_and_says_so():
    now = 1_000_000.0
    assert th.horizon_for(now, []) == th.HORIZON_H
    assert abs(th.horizon_for(now, [(now + k * 3600, 5.0) for k in range(1, 49)]) - 48.0) < 1e-9
    p, h, t_now, _ = planned_room()
    out = th.predict(p, now, t_now, 0.0, [(now + k * 3600, 5.0) for k in range(1, 49)], 5.0, 48)
    assert out["ends_at"] == round(now + 48 * 3600) and out["curve"][-1][0] == out["ends_at"]
