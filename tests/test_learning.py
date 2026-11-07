"""learning.py: running sums give the same fit as refitting on all the data, forgetting follows a drifting room, the forgetting
rate is chosen by predicting each day from the days before it, and the uncertainty narrows as days accumulate."""
import importlib.util
import math
import pathlib
import random
import sys

_pkg = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "wiser_predictive"
sys.path.insert(0, str(_pkg))  # learning.py imports thermal as a plain module here
import thermal as th  # noqa: E402

_s = importlib.util.spec_from_file_location("wiser_predictive_learning", _pkg / "learning.py")
learning = importlib.util.module_from_spec(_s)
sys.modules["wiser_predictive_learning"] = learning
_s.loader.exec_module(learning)

STEPS = th.STEPS_PER_DAY


def sim(days, tau_of_day=lambda d: 20.0, seed=1, c2=0.03, c0=0.25, reheat_every=4):
    """A room that follows the model with a time constant that may change from day to day, a 0.1 C sensor, and an outside that
    varies from day to day (so the pull of the outside can be told from the daily swing). Every reheat_every days a heat run lifts
    it back to 19 C: without that it settles at its equilibrium and goes flat, which says nothing about its cooling."""
    rng = random.Random(seed)
    day_mean = [8.0 + rng.uniform(-3, 3) for _ in range(days)]
    temps, outs, heat, t = [], [], [], 19.0
    for k in range(days * STEPS):
        d, h = k // STEPS, (k % STEPS) / 6.0
        out = day_mean[d] + 3.0 * math.sin(2 * math.pi * h / 24)
        run = d > 0 and d % reheat_every == 0 and 6.0 <= h < 7.0
        if run:
            t = 19.0
        temps.append(round(t, 1)); outs.append(out); heat.append(run)
        t += (1 / 6) * (c0 - t / tau_of_day(d) + c2 * out)
    grid = [k * th.STEP for k in range(days * STEPS)]
    return grid, temps, heat, outs


def stats_of(days, **kw):
    grid, temps, heat, outs = sim(days, **kw)
    return learning.day_stats(grid, th.cooling_windows(temps, heat, outs)), (grid, temps, heat, outs)


def test_summed_days_give_the_same_fit_as_refitting_on_all_the_windows():
    stats, (grid, temps, heat, outs) = stats_of(10)
    direct = th.fit(th.cooling_samples(temps, heat, outs))
    summed = learning.fit_days(stats, today=10, half_life=None)
    assert abs(direct.c0 - summed.c0) < 1e-6 and abs(direct.c1 - summed.c1) < 1e-8 and abs(direct.c2 - summed.c2) < 1e-6
    assert summed.n == direct.n


def test_a_day_read_again_replaces_its_stored_version_instead_of_being_added_twice():
    stats, _ = stats_of(3)
    bigger = learning.merge(stats, {1: [2.0] * 10 + [10_000.0]})
    assert bigger[1][10] == 10_000.0 and bigger[0] == stats[0] and len(bigger) == len(stats)
    partial = learning.merge(stats, {1: [2.0] * 10 + [5.0]})  # the old edge of the recorder: only part of that day is left
    assert partial[1] == stats[1]  # the full day stored earlier is kept


def test_forgetting_follows_a_room_whose_cooling_changes_and_no_forgetting_does_not():
    drift = lambda d: 20.0 if d < 20 else 10.0  # e.g. a window left open from day 20
    stats, _ = stats_of(40, tau_of_day=drift)
    forgetting = learning.fit_days(stats, today=40, half_life=7.0)
    remembering = learning.fit_days(stats, today=40, half_life=None)
    assert abs(forgetting.tau_h - 10.0) < abs(remembering.tau_h - 10.0)  # nearer the new value than the average of old and new
    assert forgetting.tau_h < 20.0 - 2.0  # it has moved off the old regime (20 h) towards the new one (10 h)


def test_the_forgetting_rate_is_chosen_by_predicting_each_day_from_the_days_before():
    drift = lambda d: 20.0 if d < 20 else 10.0
    stats, _ = stats_of(40, tau_of_day=drift)
    best, table, scored = learning.choose_half_life(stats)
    assert scored > 0 and best is not None and best <= 14.0  # a room that changed is best followed with a short memory
    steady, _tbl, _n = learning.choose_half_life(stats_of(40)[0])
    assert steady is None or steady >= 30.0  # a room that did not change needs no short memory


def test_too_few_days_to_choose_means_no_forgetting_rather_than_a_guess():
    assert learning.choose_half_life(stats_of(10)[0]) == (None, {}, 0)


def test_the_uncertainty_narrows_as_days_accumulate():
    few = learning.describe_days(stats_of(8, seed=3)[0], today=8, half_life=None)
    many = learning.describe_days(stats_of(30, seed=3)[0], today=30, half_life=None)
    assert few.tau_se_h is not None and many.tau_se_h is not None
    assert many.tau_se_h < few.tau_se_h and many.days == 30 and many.windows > few.windows


def test_too_little_data_gives_no_character():
    assert learning.describe_days(stats_of(1)[0], today=1, half_life=None) is None
