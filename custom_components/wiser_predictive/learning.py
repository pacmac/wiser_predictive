"""Continuous learning of a room's cooling (no homeassistant imports).

thermal.fit is a least-squares fit of  rate = c0 + c1*T + c2*Tout  over windows of free cooling. A least-squares fit depends on the
data only through sums (the normal equations), so each completed day can be reduced to a few sums, kept forever, and added up
again whenever the model is wanted. That is the same estimate as refitting on all the data, without keeping it, and it is what
the recursive least squares of the published online methods computes. Older days are faded by a forgetting weight so the model
follows the seasons and changes to the room. The same per-day sums give the uncertainty (leave one day out) and the choice of
forgetting rate (predict each recent day from the days before it).
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

try:
    from . import thermal
except ImportError:  # loaded as a plain module by the tests
    import thermal

DAY_S = 86400
# Forgetting half-lives tried, in days, doubling from a week; None is no forgetting. A search grid, not a derived value: the one
# in use is chosen from the data by choose_half_life.
HALF_LIVES: tuple[float | None, ...] = (7.0, 14.0, 30.0, 60.0, None)
MIN_DAYS_TO_CHOOSE = 14  # predicting a day from the days before it needs at least a fortnight, or there is nothing to compare


def day_stats(grid: Sequence[float], windows: Sequence[tuple[int, float, float, float]]) -> dict[int, list[float]]:
    """Per UTC day: [A00, A01, A02, A11, A12, A22, b0, b1, b2, yy, n], the sums of x*x^T, x*y, y*y and the count over that day's
    windows, with x = (1, T, Tout) and y the rate. A window belongs to the day it starts in."""
    out: dict[int, list[float]] = {}
    for i, t, o, y in windows:
        d = int(grid[i] // DAY_S)
        s = out.setdefault(d, [0.0] * 11)
        s[0] += 1.0; s[1] += t; s[2] += o; s[3] += t * t; s[4] += t * o; s[5] += o * o
        s[6] += y; s[7] += t * y; s[8] += o * y; s[9] += y * y; s[10] += 1.0
    return out


def merge(stored: Mapping[int, Sequence[float]], fresh: Mapping[int, Sequence[float]]) -> dict[int, list[float]]:
    """The stored days with each day in `fresh` taking its place (a re-read of the same day is not added twice). The version with
    more windows wins: at the old edge of the recorder's history a day is only partly there, and that partial re-read must not
    replace the full day that was stored when it was complete."""
    out = {int(d): list(s) for d, s in stored.items()}
    for d, s in fresh.items():
        if int(d) not in out or s[10] >= out[int(d)][10]:
            out[int(d)] = list(s)
    return out


def _weights(days: Sequence[int], today: int, half_life: float | None) -> dict[int, float]:
    return {d: 1.0 if half_life is None else 0.5 ** (max(0, today - d) / half_life) for d in days}


def _combine(stats: Mapping[int, Sequence[float]], w: Mapping[int, float], skip: int | None = None):
    tot = [0.0] * 11
    for d, s in stats.items():
        if d == skip or d not in w:
            continue
        for k in range(11):
            tot[k] += w[d] * s[k]
    return tot


def _fit(tot: Sequence[float], min_n: float) -> thermal.Params | None:
    n = tot[10]
    if n < min_n:
        return None
    a = [[tot[0], tot[1], tot[2]], [tot[1], tot[3], tot[4]], [tot[2], tot[4], tot[5]]]
    x = thermal._solve(a, [tot[6], tot[7], tot[8]])
    if x is None or x[1] >= 0 or -1.0 / x[1] > thermal.MAX_TAU_H:
        return None
    return thermal.Params(x[0], x[1], x[2], int(round(n)))


def fit_days(stats: Mapping[int, Sequence[float]], today: int, half_life: float | None) -> thermal.Params | None:
    return _fit(_combine(stats, _weights(list(stats), today, half_life)), thermal.MIN_SAMPLES)


def describe_days(stats: Mapping[int, Sequence[float]], today: int, half_life: float | None) -> thermal.Character | None:
    """The room's thermal character from every day kept, with a leave-one-day-out uncertainty. The windows count is the number of
    windows, not the weighted number, so it says how much has been learned from."""
    w = _weights(list(stats), today, half_life)
    p = _fit(_combine(stats, w), thermal.MIN_SAMPLES)
    if p is None:
        return None
    taus, couplings = [], []
    for d in stats:
        q = _fit(_combine(stats, w, skip=d), thermal.MIN_SAMPLES)
        if q is not None:
            taus.append(q.tau_h)
            couplings.append(q.c2 / -q.c1)

    def jackknife(xs: list[float]) -> float | None:
        k = len(xs)
        if k < 3:
            return None
        m = sum(xs) / k
        return math.sqrt((k - 1) / k * sum((x - m) ** 2 for x in xs))

    omega = 2 * math.pi / 24.0
    coupling = p.c2 / -p.c1
    return thermal.Character(
        tau_h=p.tau_h, tau_se_h=jackknife(taus), coupling=coupling, coupling_se=jackknife(couplings),
        delay_h=math.atan(omega * p.tau_h) / omega, damping=coupling / math.sqrt(1 + (omega * p.tau_h) ** 2),
        windows=int(sum(s[10] for s in stats.values())), days=len(stats), settles={o: p.equilibrium(float(o)) for o in (5, 8, 11)},
    )


def _day_error(p: thermal.Params, s: Sequence[float]) -> float:
    """Mean squared error of the model's rate on one day's windows, from that day's sums: sum (y - x.theta)^2 / n."""
    th = (p.c0, p.c1, p.c2)
    a = [[s[0], s[1], s[2]], [s[1], s[3], s[4]], [s[2], s[4], s[5]]]
    b = (s[6], s[7], s[8])
    quad = sum(th[i] * a[i][j] * th[j] for i in range(3) for j in range(3))
    return max(0.0, (s[9] - 2 * sum(th[i] * b[i] for i in range(3)) + quad) / s[10]) if s[10] else 0.0


def choose_half_life(stats: Mapping[int, Sequence[float]], candidates: Sequence[float | None] = HALF_LIVES):
    """Which forgetting rate predicts the next day best: for each of the last days, fit on the days before it with each candidate
    half-life and score the fit on that day's windows. Returns (half-life or None for no forgetting, {candidate: mean error}, days
    scored). With fewer than MIN_DAYS_TO_CHOOSE days there is nothing to compare, so it returns (None, {}, 0): no forgetting."""
    days = sorted(stats)
    if len(days) < MIN_DAYS_TO_CHOOSE:
        return None, {}, 0
    test_days = days[len(days) // 2:]  # score the later half, each predicted from the days before it
    table: dict[float | None, float] = {}
    for h in candidates:
        errs = []
        for d in test_days:
            earlier = {k: stats[k] for k in days if k < d}
            p = fit_days(earlier, d, h)
            if p is not None and stats[d][10] >= 1:
                errs.append(_day_error(p, stats[d]))
        if errs:
            table[h] = sum(errs) / len(errs)
    if not table:
        return None, {}, 0
    return min(table, key=table.get), table, len(test_days)


def summarise(stats: Mapping[int, Sequence[float]], today: int):
    """Everything the panel needs from the days kept: the character, the model parameters, and how it was learned. The forgetting
    rate is chosen from the completed days (those before today). None when there is too little free cooling to fit."""
    complete = {d: s for d, s in stats.items() if d < today}
    half_life, _table, scored = choose_half_life(complete)
    character = describe_days(stats, today, half_life)
    params = fit_days(stats, today, half_life)
    if character is None or params is None:
        return None
    return {
        "character": character, "params": params,
        "info": {"days": len(stats), "half_life_days": half_life, "chosen_by_days": scored, "windows": int(sum(s[10] for s in stats.values()))},
    }
