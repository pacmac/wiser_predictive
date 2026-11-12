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

TMAX, TAU_MIN, LAG_MIN = 19.0, 80.0, 20.0


def rows_with_runs(minutes_list, gap_h=30.0, t0=12.6):
    """A room history: heat runs (demand 100%) of the given lengths, each starting gap_h after the last. The room follows the
    lagged heating model (TMAX, TAU_MIN, LAG_MIN), read every minute to 0.1 C like the real sensors, until it has settled."""
    rows, now_t = [(0.0, {"current_temperature": t0, "is_heating": False, "percentage_demand": 0})], 0.0
    for m in minutes_list:
        now_t += gap_h * 3600
        rows.append((now_t - 3600, {"current_temperature": t0, "is_heating": False, "percentage_demand": 0}))  # cooled back down
        x, t = 0.0, t0
        for k in range(0, m + 2 * th.SETTLED_S // 60 + 1):
            on = k < m
            x += ((1.0 if on else 0.0) - x) / LAG_MIN
            t += x * (TMAX - t) / TAU_MIN
            rows.append((now_t + k * 60, {"current_temperature": round(t, 1) if k else t0, "is_heating": on, "percentage_demand": 100 if on else 0}))
    return rows


def test_runs_are_found_with_their_full_demand_minutes_and_settled_lift():
    found = th.runs(rows_with_runs([15, 15, 40]))
    assert [round(r["minutes"]) for r in found] == [15, 15, 40]
    assert all(abs(r["before"] - 12.6) < 1e-9 for r in found)
    truth = th.Heating(TMAX, TAU_MIN, 8, 0.0, LAG_MIN)
    assert abs(found[0]["settled"] - (12.6 + th.heat_lift(truth, 12.6, 15))) < 0.15


def test_the_heating_fit_recovers_the_curve_and_the_radiator_lag_from_runs_of_different_lengths():
    h = th.fit_heating(th.runs(rows_with_runs([10, 15, 15, 20, 40, 90, 150])))
    assert h is not None and h.rms < 0.1
    assert abs(h.tmax - TMAX) < 0.6 and abs(h.tau_min - TAU_MIN) < 12 and abs(h.lag_min - LAG_MIN) < 5, h


def test_a_short_run_barely_shows_at_first_and_arrives_later():
    """The cold start that exposed the old curve: with a radiator lag, 15 minutes of heat shows under +0.2 C after 10 minutes and
    more than five times that once the radiator has run out."""
    h = th.Heating(18.5, 60.0, 9, 0.2, 25.0)
    path = th.heat_path(h, 12.6, 15)
    assert path[0] - 12.6 < 0.2 and path[-1] - 12.6 > 1.0
    assert path[-1] - 12.6 == th.heat_lift(h, 12.6, 15)
    assert all(b >= a for a, b in zip(path, path[1:]))  # the room does not fall while heat is arriving
    plain = th.Heating(18.5, 60.0, 9, 0.2, 1.0)
    assert th.heat_path(plain, 12.6, 15)[0] - 12.6 > 0.8  # with no lag the same dose would show at once


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


def test_with_a_radiator_lag_the_plan_draws_the_room_rising_over_time_not_jumping():
    p, _, t_now, _ = planned_room()
    h = th.Heating(TMAX, TAU_MIN, 8, 0.0, LAG_MIN)
    now, forecast = 1_000_000.0, [(1_000_000.0 + k * 3600, 2.0) for k in range(1, 49)]
    minimum = t_now - 0.5
    plan = th.plan(p, h, now, t_now, minimum, forecast, 2.0, horizon_h=48)
    first = plan["runs"][0]
    assert first["minutes"] % th.RUN_STEP_MIN == 0
    near = [v for t, v in plan["curve"] if first["call_by"] <= t <= first["call_by"] + 1800]
    assert near and max(near) < first["lifts_to"] - 0.3  # half an hour after the call the heat has not all arrived
    assert min(v for _, v in plan["curve"]) > minimum - 0.15


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


def test_describe_gives_the_published_quantities_and_an_uncertainty():
    c = th.describe(th.cooling_windows(*room(10 * 24)))
    omega = 2 * math.pi / 24
    assert c is not None and abs(c.tau_h - TAU) < 1.0                       # thermal time constant
    assert abs(c.coupling - C2 * TAU) < 0.05                                 # degrees of room per degree of outside: 0.03 * 20 = 0.6
    assert abs(c.delay_h - math.atan(omega * TAU) / omega) < 0.3             # a daily swing arrives about 5.3 h late
    assert abs(c.damping - c.coupling / math.sqrt(1 + (omega * TAU) ** 2)) < 0.02
    assert c.tau_se_h is not None and c.tau_se_h < 2.0 and c.days == 10      # a clean synthetic room is well determined
    assert abs(c.settles[8] - (-(C0 + C2 * 8.0) / C1)) < 0.5


def test_describe_has_no_uncertainty_from_fewer_than_four_days_and_nothing_from_too_little():
    few = th.describe(th.cooling_windows(*room(2 * 24)))
    assert few is None or few.tau_se_h is None
    assert th.describe(th.cooling_windows(*room(10))) is None


def test_a_run_is_two_radiator_lags_not_enough_to_hold_the_whole_forecast_and_carries_its_target():
    # The old rule (the shortest dose that holds to the end of a 48 h forecast) planned the longest dose, 3 time constants; per hour
    # held that costs many times a short run. The dose is now DOSE_LAGS lags rounded up to the 5 min step, repeated when needed.
    p, _, t_now, _ = planned_room()
    h = th.Heating(TMAX, TAU_MIN, 8, 0.0, LAG_MIN)
    now, forecast = 1_000_000.0, [(1_000_000.0 + k * 3600, 2.0) for k in range(1, 49)]
    minimum = t_now - 0.5
    plan = th.plan(p, h, now, t_now, minimum, forecast, 2.0, horizon_h=48)
    dose = 2 * LAG_MIN  # 40 min: a multiple of the 5 min step already
    assert plan["runs"] and all(r["minutes"] == dose for r in plan["runs"])
    longest = round(3 * TAU_MIN / th.RUN_STEP_MIN) * th.RUN_STEP_MIN
    assert dose < longest
    first = plan["runs"][0]
    # the target keeps demand at 100% to the end of the dose: it is at least 1.6 C above the room when the dose ends, in 0.5 C steps
    assert first["target"] % th.SETPOINT_STEP == 0 and first["target"] > minimum + th.FULL_DEMAND_GAP - 1e-9
    assert min(v for _, v in plan["curve"]) > minimum - 0.15  # shorter runs still never let the room fall below the minimum


def test_the_dose_rounds_two_lags_up_to_the_five_minute_step():
    p, _, t_now, _ = planned_room()
    now, forecast = 1_000_000.0, [(1_000_000.0 + k * 3600, 2.0) for k in range(1, 49)]
    for lag, expect in ((14.0, 30), (1.0, 5), (6.0, 15)):
        h = th.Heating(TMAX, TAU_MIN, 8, 0.0, lag)
        plan = th.plan(p, h, now, t_now, t_now - 0.5, forecast, 2.0, horizon_h=48)
        assert plan["runs"][0]["minutes"] == expect, lag


def rows_with_a_fast_fall(n_runs, drop, tau_h, gap_h=14.0, outside_c=5.0):
    """A room history of 30-minute boosts, each followed by cooling by the known model (C0, C1, C2) plus an extra warmth `drop` that
    dies away with time constant tau_h from the settle point (SETTLE steps after the heat). Returns (climate rows, outside series)."""
    rows, outside, now_t, base = [], [], 1_000_200.0, 12.0  # a multiple of STEP, so the rows sit on the model's grid
    cycle, dose = int(gap_h * 3600 / th.STEP), 3
    for _ in range(n_runs):
        for k in range(cycle):
            since = k - dose - th.SETTLE  # steps since the settle point; negative before it
            if k >= dose + th.SETTLE:
                base += th.STEP / 3600 * (C0 + C1 * base + C2 * outside_c)
            shown = base + (drop if since < 0 else drop * math.exp(-since * th.STEP / 3600 / tau_h))
            on = k < dose
            rows.append((now_t, {"current_temperature": round(shown, 2), "is_heating": on, "percentage_demand": 100 if on else 0}))
            outside.append((now_t, outside_c))
            now_t += th.STEP
        base = 12.0
    return rows, outside


def test_the_extra_fall_after_a_boost_is_found_from_the_boosts_in_the_history():
    # Measured on the lounge, 10 boosts in 10 days: the room (as the valve sensor sees it) falls 0.3 to 0.4 C more in the first hours
    # than the plain cooling model says, with a time constant near an hour. The history here has exactly that, 0.4 C over 1 h.
    climate, outside = rows_with_a_fast_fall(8, drop=0.4, tau_h=1.0)
    p = th.Params(C0, C1, C2, 500)
    found = th.fit_after_run(climate, outside, p)
    assert found is not None
    drop, tau_h = found
    # The cooling model also cools the warm excess (tau 20 h here), so the measured gap tops out near 0.33 and then slips: the fit
    # reads about 0.3 arriving inside an hour, which is the history's 0.4 over 1 h as the model sees it.
    assert 0.25 < drop < 0.45 and tau_h <= 1.0


def test_no_extra_fall_is_claimed_from_too_few_boosts():
    climate, outside = rows_with_a_fast_fall(th.MIN_RUNS - 1, drop=0.4, tau_h=1.0)
    assert th.fit_after_run(climate, outside, th.Params(C0, C1, C2, 500)) is None


def test_a_room_that_falls_as_the_model_says_gets_no_extra_fall():
    climate, outside = rows_with_a_fast_fall(8, drop=0.0, tau_h=1.0)
    found = th.fit_after_run(climate, outside, th.Params(C0, C1, C2, 500))
    assert found is not None and abs(found[0]) < 0.05


def test_the_plan_cools_the_room_faster_after_a_run_when_the_room_does_and_calls_for_the_next_run_sooner():
    import dataclasses
    p, _, t_now, _ = planned_room()
    plain = th.Heating(TMAX, TAU_MIN, 8, 0.0, LAG_MIN)
    fast = dataclasses.replace(plain, drop=0.4, drop_tau_h=1.0)
    now, forecast = 1_000_000.0, [(1_000_000.0 + k * 3600, 2.0) for k in range(1, 49)]
    a = th.plan(p, plain, now, t_now, t_now - 0.5, forecast, 2.0, horizon_h=48)
    b = th.plan(p, fast, now, t_now, t_now - 0.5, forecast, 2.0, horizon_h=48)
    assert a["runs"][0]["call_by"] == b["runs"][0]["call_by"]  # the first run is called when the room reaches the minimum, either way
    assert b["runs"][0]["holds_until"] < a["runs"][0]["holds_until"]  # but it holds for less time
    assert th.Heating(TMAX, TAU_MIN, 8, 0.0).drop == 0.0  # a model that has not learned the fall adds none
