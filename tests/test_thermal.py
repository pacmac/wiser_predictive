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
