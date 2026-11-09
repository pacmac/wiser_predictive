"""Pure thermal model of one room (no homeassistant imports). Learned from the recorded history, used to predict.

A room with its heating off cools toward an equilibrium that depends on the outside temperature:

    dT/dt = c0 + c1*T + c2*Tout            (c1 < 0)

so the cooling time constant is tau = -1/c1 and the equilibrium is Teq(Tout) = -(c0 + c2*Tout)/c1. The constant c0 is what the
house adds (other rooms, gains); c2 is how strongly the outside pulls. It is fitted by least squares on the history,
using only periods when the room had free cooling (no heating, and not just after it). Times are seconds, temperatures C.
docs/SPEC.md, MODEL. Measured in replay.py --model against "the temperature stays where it is".
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Sequence

STEP = 600  # seconds between samples: finer than the 0.1 C sensors resolve over a window, coarse enough to stay light
SETTLE = 6  # steps (60 min) after heating ends before a sample counts. Valve-mounted sensors read the warm radiator for a while;
# in the replay tau stopped changing from 30 min (20.8 h) to 90 min (20.9 h) in the lounge, so 30 min is on the plateau and
# 60 min is twice that. Longer than 120 min starts to throw away the fast-cooling samples and the fit drifts.
WINDOW = 6  # steps (60 min): the rate is the change over an hour, so the 0.1 C sensor step is 0.1 C/h, small against the usual 0.05-0.5 C/h
MIN_SAMPLES = 144  # one day of 10-minute samples: the outside temperature swings once a day, so less than a day cannot tell the
# pull of the outside from the daily swing
MAX_TAU_H = 200.0  # a fitted time constant longer than this is a flat line, not a cooling curve


@dataclass(frozen=True)
class Params:
    c0: float
    c1: float
    c2: float
    n: int  # samples the fit used

    @property
    def tau_h(self) -> float:
        return -1.0 / self.c1

    def equilibrium(self, tout: float) -> float:
        return -(self.c0 + self.c2 * tout) / self.c1


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(a[r][i]))
        if abs(a[p][i]) < 1e-12:
            return None
        a[i], a[p], b[i], b[p] = a[p], a[i], b[p], b[i]
        for r in range(i + 1, n):
            f = a[r][i] / a[i][i]
            for c in range(i, n):
                a[r][c] -= f * a[i][c]
            b[r] -= f * b[i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (b[i] - sum(a[i][c] * x[c] for c in range(i + 1, n))) / a[i][i]
    return x


def cooling_samples(
    temps: Sequence[float | None], heating: Sequence[bool], outside: Sequence[float | None]
) -> list[tuple[float, float, float]]:
    """(T at the start, mean outside over the window, rate C/h) for every window of free cooling (see cooling_windows)."""
    return [(t, o, r) for _, t, o, r in cooling_windows(temps, heating, outside)]


def cooling_windows(
    temps: Sequence[float | None], heating: Sequence[bool], outside: Sequence[float | None]
) -> list[tuple[int, float, float, float]]:
    """(grid index of the start, T at the start, mean outside over the window, rate C/h) for every window of free cooling.
    The three sequences share one time grid of STEP seconds. A window counts when the heating was off for SETTLE steps before it
    and all through it, and the temperature and outside are known throughout."""
    n = len(temps)
    out: list[tuple[int, float, float, float]] = []
    since, last = [], -10**9
    for i in range(n):
        if heating[i]:
            last = i
        since.append(i - last)
    for i in range(n - WINDOW):
        end = i + WINDOW
        if since[i] < SETTLE or any(heating[i:end + 1]):
            continue
        outs = outside[i:end + 1]
        if temps[i] is None or temps[end] is None or any(o is None for o in outs):
            continue
        out.append((i, temps[i], sum(outs) / len(outs), (temps[end] - temps[i]) / (WINDOW * STEP / 3600.0)))
    return out


# --- what the room is like: the published quantities, with an honest uncertainty ------------------------------------------

STEPS_PER_DAY = 86400 // STEP


@dataclass(frozen=True)
class Character:
    """The room's thermal character. tau_h is the thermal time constant (total thermal capacitance / total heat loss coefficient,
    C/HTC): the time to cover 63.2% of a step change. coupling is the degrees the settled room temperature moves per degree of
    outside, so below 1 means heat is also exchanged with neighbours or gained inside. delay_h and damping say what a daily outside
    swing becomes inside: the time lag and (here as a ratio of the outside swing) the decrement. *_se are leave-one-day-out
    standard errors, None with fewer than four days."""

    tau_h: float
    tau_se_h: float | None
    coupling: float
    coupling_se: float | None
    delay_h: float
    damping: float
    windows: int
    days: int
    settles: dict[int, float]  # settled room temperature at 5, 8 and 11 C outside


def describe(windows: Sequence[tuple[int, float, float, float]]) -> Character | None:
    """Fit the room from its free-cooling windows and say what it is like; None if there is too little to fit."""
    p = fit([(t, o, r) for _, t, o, r in windows])
    if p is None:
        return None
    days = sorted({i // STEPS_PER_DAY for i, *_ in windows})
    taus, couplings = [], []
    for d in days:  # leave one day out and refit: how much the answer depends on any one day
        q = fit([(t, o, r) for i, t, o, r in windows if i // STEPS_PER_DAY != d])
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
    return Character(
        tau_h=p.tau_h, tau_se_h=jackknife(taus), coupling=coupling, coupling_se=jackknife(couplings),
        delay_h=math.atan(omega * p.tau_h) / omega, damping=coupling / math.sqrt(1 + (omega * p.tau_h) ** 2),
        windows=p.n, days=len(days), settles={o: p.equilibrium(float(o)) for o in (5, 8, 11)},
    )


def fit(samples: Sequence[tuple[float, float, float]]) -> Params | None:
    """None when there is not enough free cooling to learn from, or the result is not a cooling curve."""
    if len(samples) < MIN_SAMPLES:
        return None
    rows = [(1.0, t, o) for t, o, _ in samples]
    y = [r for _, _, r in samples]
    a = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    b = [sum(r[i] * yy for r, yy in zip(rows, y)) for i in range(3)]
    x = _solve(a, b)
    if x is None or x[1] >= 0 or -1.0 / x[1] > MAX_TAU_H:
        return None
    return Params(x[0], x[1], x[2], len(samples))


def simulate(p: Params, t0: float, outside: Sequence[float]) -> list[float]:
    """The temperature after each STEP, from t0, if no heat is supplied, for the given outside temperature at each step."""
    t, out, dt = t0, [], STEP / 3600.0
    for o in outside:
        t += dt * (p.c0 + p.c1 * t + p.c2 * o)
        out.append(t)
    return out


def steps_to_reach(path: Sequence[float], minimum: float) -> int | None:
    """Index (1-based, in STEPs) of the first point at or below the minimum, or None if the path stays above it."""
    for i, v in enumerate(path):
        if v <= minimum:
            return i + 1
    return None


# --- from recorded rows to the model's grid, and a prediction -------------------------------------------------------------

LEAD_S = 8 * 60  # seconds from calling for heat until the room has stopped falling. Measured on the lounge's boosts: the room
# fell no further than one 0.1 C sensor step after the call, and the first measurable rise (+0.1 C) took 0.5-7.2 min (7 boosts).
# 7.2 min rounded up to 8. It does not include the delay of whatever sends the call.
CURVE_STEP_S = 1800  # the drawn prediction has a point every 30 min: the room moves tenths of a degree an hour, so this is smooth
HORIZON_H = 24
FLOOR_HELD_S = 3600  # a setpoint counts as the room's floor only if it was held for an hour or more in the history: a boost
# lasts 14-15 min, so anything shorter is a boost or a blip and not a schedule level


def _held(points: Sequence[tuple[float, float]], grid: Sequence[float]) -> list[float | None]:
    out, i, v = [], 0, None
    for g in grid:
        while i < len(points) and points[i][0] <= g:
            v = points[i][1]
            i += 1
        out.append(v)
    return out


def _linear(points: Sequence[tuple[float, float]], grid: Sequence[float]) -> list[float | None]:
    out, j = [], 0
    for g in grid:
        while j + 1 < len(points) and points[j + 1][0] <= g:
            j += 1
        if not points or g < points[0][0]:
            out.append(None)
        elif j + 1 >= len(points):
            out.append(points[-1][1])
        else:
            (a, va), (b, vb) = points[j], points[j + 1]
            out.append(va + (vb - va) * (g - a) / (b - a) if b > a else va)
    return out


def prepare(climate, outside):
    """climate: [(seconds, attributes)] of the room's climate entity; outside: [(seconds, C)].
    Returns (grid, temps, heating, outs) on the model's grid (STEP seconds), or None if either has no data."""
    rows = sorted(climate, key=lambda r: r[0])
    out = sorted(outside)
    if not rows or not out:
        return None
    start = max(rows[0][0], out[0][0])
    t0 = -(-start // STEP) * STEP
    n = int((rows[-1][0] - t0) // STEP)
    if n <= 0:
        return None
    grid = [t0 + k * STEP for k in range(n)]
    reading = [(t, float(a["current_temperature"])) for t, a in rows if a.get("current_temperature") is not None]
    flags = [(t, bool(a.get("is_heating")) or bool(a.get("is_boosted")) or (a.get("percentage_demand") or 0) > 0) for t, a in rows]
    heating = [bool(h) for h in _held([(t, float(f)) for t, f in flags], grid)]
    return grid, _held(reading, grid), heating, _linear(out, grid)


def held_floor(climate, min_seconds: float = FLOOR_HELD_S) -> float | None:
    """The lowest target the thermostat held for at least min_seconds in total: the floor of a room that has no LOW setting."""
    rows = sorted((t, a.get("temperature")) for t, a in climate)
    held: dict[float, float] = {}
    for (t0, v), (t1, _) in zip(rows, rows[1:]):
        if v is not None:
            held[float(v)] = held.get(float(v), 0.0) + (t1 - t0)
    ok = [v for v, s in held.items() if s >= min_seconds]
    return min(ok) if ok else None


def outside_path(last: float | None, now: float, forecast: Sequence[tuple[float, float]], steps: int) -> list[float | None]:
    """The outside temperature at each STEP after now: from the last measured value, along the hourly forecast, then held."""
    pts = ([(now, last)] if last is not None else []) + sorted((t, v) for t, v in forecast if t > now)
    return _linear(pts, [now + (k + 1) * STEP for k in range(steps)])


def horizon_for(now: float, forecast) -> float:
    """Hours to predict: as far as the forecast goes (the weather service's hourly forecast is 48 h), else HORIZON_H. Beyond the
    last forecast hour the outside temperature is unknown, so the prediction stops there instead of guessing."""
    ahead = [t for t, _ in forecast if t > now]
    return float(HORIZON_H) if not ahead else max(1.0, (max(ahead) - now) / 3600.0)


def predict(p: Params, now: float, temp_now: float, minimum: float, forecast, last_outside: float | None, horizon_h: float = HORIZON_H) -> dict:
    """If no heat is supplied from now: the room's curve for the next horizon_h, when it reaches the minimum, the latest moment
    to call for heat (LEAD_S earlier), and the lowest point. Needs the outside path (measured now, then the forecast)."""
    steps = int(horizon_h * 3600 // STEP)
    outs = outside_path(last_outside, now, forecast, steps)
    if any(o is None for o in outs):
        return {"error": "no outside temperature to predict with"}
    path = simulate(p, temp_now, outs)
    k = steps_to_reach(path, minimum)
    per = CURVE_STEP_S // STEP
    curve = [[round(now), round(temp_now, 2)]] + [[round(now + (i + 1) * STEP), round(v, 2)] for i, v in enumerate(path) if (i + 1) % per == 0]
    low_i = min(range(len(path)), key=lambda i: path[i])
    reaches = None if k is None else round(now + k * STEP)
    return {
        "ends_at": round(now + steps * STEP), "falling_at_end": len(path) > 1 and path[-1] < path[-2],
        "minimum": minimum, "curve": curve, "reaches_at": reaches,
        "call_by": None if reaches is None else max(round(now), reaches - LEAD_S),
        "lowest": [round(now + (low_i + 1) * STEP), round(path[low_i], 2)],
        "lead_s": LEAD_S, "tau_h": round(p.tau_h, 1), "windows": p.n,
        "outside_low": min(((t, v) for t, v in forecast if t > now), key=lambda x: x[1], default=None),
    }


# --- the heating response, and a plan: when to heat and for how long -------------------------------------------------------
# While heat is supplied the room heads for a maximum with a time constant: T(m) = Tmax - (Tmax - T0) * exp(-m / tau_h), m in
# minutes of heating at full demand. Measured on the lounge's runs: one curve fitted on eight 15-minute boosts predicted the
# held-out 175-minute run (18.5 C predicted, 18.5 C observed). Stored heat then decays with the cooling time constant, so the
# cheapest moment to heat is the latest safe one: heat delivered earlier has longer to leak away.

RUN_GAP_S = 20 * 60  # seconds. Two heating periods closer than this are one run: a boost lasts 14-15 min, so a boost
# followed by another within 20 min is a continuation, while separate runs in the history were hours apart
SETTLED_S = SETTLE * STEP  # the reading is taken this long after a run ends, once the warm radiator has stopped biasing the sensor
MIN_RUNS = 4  # two numbers are fitted (the maximum and the time constant); fewer than twice that many runs cannot tell them apart
TAU_H_RANGE = (20.0, 240.0)  # minutes searched for the heating time constant: shorter than a boost cannot be seen, and a run
# longer than 4 hours is not a normal heat-up
RUN_STEP_MIN = 5  # the plan is in 5-minute doses: finer than the heat call can be timed
MAX_RUNS = 4  # runs planned inside one 24 h horizon; more means the room cannot be held by heating at all


LAGS_MIN = (1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0)  # search grid for the radiator lag, minutes:
# from 1 (no lag: heat reaches the room the minute it is called) to SETTLED_S/60 = 60 (a lag longer than the settle time could not be seen)
PATH_FROM_MIN = 10  # fit from 10 min into a run: the first sensor step (0.1 C) can take up to 7.2 min to show (see LEAD_S)
PATH_EVERY_MIN = 5  # compare the fitted path with the readings every 5 min: the climate entity updates about every 2 min


@dataclass(frozen=True)
class Heating:
    """While heat is called for, a fraction x of full emission reaches the room, following the demand u with the radiator's lag:
    dx/dt = (u - x) / lag, and the room heads for tmax at a rate x: dT/dt = x * (tmax - T) / tau. With lag = 1 minute this is the
    plain exponential T(m) = tmax - (tmax - T0) * exp(-m / tau). The lag is why a 15-minute boost shows +0.3 C at 15 minutes and
    +1.2 C an hour later (Saturday 2026-11-07 07:01 UTC and the boosts before it)."""
    tmax: float  # C the room heads for at full demand
    tau_min: float  # minutes
    runs: int  # runs the fit used
    rms: float  # C: how far the fit is from the runs it learned from
    lag_min: float = 1.0  # minutes: the radiator's lag


def heat_path(h: Heating, t0: float, minutes: float) -> list[float]:
    """The room's temperature at each STEP after a heat call at full demand for `minutes`, from t0, until the radiator has run out
    (5 lags: the emission is then below 1%). 1-minute integration; no cooling term, because the fit's maximum already includes
    the losses."""
    per = STEP // 60
    total = int(math.ceil(minutes + 5.0 * h.lag_min))
    total = -(-total // per) * per
    x, t, out = 0.0, t0, []
    for k in range(1, total + 1):
        x += ((1.0 if k <= minutes else 0.0) - x) / h.lag_min
        t += x * (h.tmax - t) / h.tau_min
        if k % per == 0:
            out.append(t)
    return out


def heat_lift(h: Heating, t0: float, minutes: float) -> float:
    """The settled lift (C) from `minutes` of full demand: where the room ends up once the radiator has run out."""
    return heat_path(h, t0, minutes)[-1] - t0


def runs(climate) -> list[dict]:
    """The heat runs in a room's history: {start, end, minutes (at full demand), before, settled} in seconds and C. A run is the
    heating, boost or demand flags on, with gaps under RUN_GAP_S closed. Only runs with a reading before and SETTLED_S after
    (no heating in between) are kept."""
    rows = sorted(climate, key=lambda r: r[0])
    if len(rows) < 3:
        return []
    on = [bool(a.get("is_heating")) or bool(a.get("is_boosted")) or (a.get("percentage_demand") or 0) > 0 for _, a in rows]
    reading = [(t, float(a["current_temperature"])) for t, a in rows if a.get("current_temperature") is not None]

    def at(t: float) -> float | None:
        v = None
        for tt, x in reading:
            if tt > t:
                break
            v = x
        return v

    out, i, n = [], 0, len(rows)
    while i < n:
        if not on[i]:
            i += 1
            continue
        start, last_on, j = rows[i][0], i, i
        while j < n and (on[j] or rows[j][0] - rows[last_on + 1][0] <= RUN_GAP_S if last_on + 1 < n else False):
            if on[j]:
                last_on = j
            j += 1
            if j < n and not on[j] and rows[j][0] - rows[last_on + 1][0] > RUN_GAP_S:
                break
        end = rows[last_on + 1][0] if last_on + 1 < n else rows[last_on][0]
        minutes = sum(((rows[k][1].get("percentage_demand") or 0) / 100.0) * (rows[k + 1][0] - rows[k][0]) / 60.0
                      for k in range(i, min(last_on + 1, n - 1)) if on[k])
        before, settled = at(start - 1), at(end + SETTLED_S)
        later = rows[-1][0] >= end + SETTLED_S
        clear = not any(on[k] for k in range(last_on + 1, n) if rows[k][0] <= end + SETTLED_S)
        if before is not None and settled is not None and later and clear and minutes > 0:
            u, temps = _minute_path(rows, start - 60, end + SETTLED_S)
            out.append({"start": start, "end": end, "minutes": minutes, "before": before, "settled": settled, "path": (u, temps)})
        i = max(last_on + 1, i + 1)
    return out


def _minute_path(rows, t0: float, t1: float) -> tuple[list[float], list[float | None]]:
    """The demand (0-1) and the room reading at every minute from t0 to t1, each carried forward from the last row at or before it.
    Demand counts only while heating, boost or demand is on, as in `runs`."""
    times = [t for t, _ in rows]
    j = bisect.bisect_right(times, t0)
    u, temp = 0.0, None
    if j:
        a = rows[j - 1][1]
        on = bool(a.get("is_heating")) or bool(a.get("is_boosted")) or (a.get("percentage_demand") or 0) > 0
        u, temp = ((a.get("percentage_demand") or 0) / 100.0 if on else 0.0), a.get("current_temperature")
    us, ts = [], []
    for t in range(int(t0), int(t1), 60):
        while j < len(rows) and rows[j][0] <= t:
            a = rows[j][1]
            if a.get("current_temperature") is not None:
                temp = a["current_temperature"]
            on = bool(a.get("is_heating")) or bool(a.get("is_boosted")) or (a.get("percentage_demand") or 0) > 0
            u = (a.get("percentage_demand") or 0) / 100.0 if on else 0.0
            j += 1
        us.append(u)
        ts.append(None if temp is None else float(temp))
    return us, ts


def _path_error(found: Sequence[dict], tmax: float, tau: float, lag: float) -> tuple[float, int]:
    """Sum of squared errors, and the number of readings compared, of the heating model's path against every run's readings."""
    sq, n = 0.0, 0
    for r in found:
        u, temps = r["path"]
        x, t = 0.0, temps[0]
        for k, ui in enumerate(u):
            x += (ui - x) / lag
            t += x * (tmax - t) / tau
            if k >= PATH_FROM_MIN and k % PATH_EVERY_MIN == 0 and temps[k] is not None:
                sq += (t - temps[k]) ** 2
                n += 1
    return sq, n


def fit_heating(found: Sequence[dict]) -> Heating | None:
    """Fit the maximum, time constant and radiator lag to the whole path of every run (not only where it ended): coarse grid, then
    a finer search around the best. None with fewer than MIN_RUNS. Runs without a path (rows made by hand) are fitted on the settled
    lift alone, with no lag."""
    if len(found) < MIN_RUNS:
        return None
    key = tuple((r["start"], r["end"], r["settled"]) for r in found)  # the same runs give the same fit: the panel asks every 5 minutes
    if _FIT_CACHE[0] == key:
        return _FIT_CACHE[1]
    result = _fit_heating(found)
    _FIT_CACHE[:] = [key, result]
    return result


_FIT_CACHE: list = [None, None]


def _fit_heating(found: Sequence[dict]) -> Heating | None:
    top = max(max(r["settled"], r["before"]) for r in found)
    if not all("path" in r for r in found):
        best: tuple[float, float, float] | None = None
        tmax = top + 0.1
        while tmax <= top + 8.0:  # the maximum is above anything seen and within 8 C of it
            tau = TAU_H_RANGE[0]
            while tau <= TAU_H_RANGE[1]:
                sq = sum(((tmax - r["before"]) * (1 - math.exp(-r["minutes"] / tau)) - (r["settled"] - r["before"])) ** 2 for r in found)
                if best is None or sq < best[0]:
                    best = (sq, tmax, tau)
                tau += 2.0
            tmax += 0.1
        assert best is not None
        return Heating(round(best[1], 1), best[2], len(found), math.sqrt(best[0] / len(found)))

    best_p: tuple[float, float, float, float] | None = None

    def consider(tmax: float, tau: float, lag: float) -> None:
        nonlocal best_p
        sq, n = _path_error(found, tmax, tau, lag)
        if n and (best_p is None or sq / n < best_p[0]):
            best_p = (sq / n, tmax, tau, lag)

    tmax = top + 0.2
    while tmax <= top + 8.0:  # the maximum is above anything seen and within 8 C of it
        tau = TAU_H_RANGE[0]
        while tau <= TAU_H_RANGE[1]:
            for lag in LAGS_MIN:
                consider(tmax, tau, lag)
            tau += 10.0
        tmax += 0.5
    if best_p is None:
        return None
    _, t0, tau0, lag0 = best_p  # refine: one coarse step either side of the best, in finer steps
    for i in range(-5, 6):
        for j in range(-5, 6):
            for lag in {max(1.0, lag0 + d) for d in range(-5, 6)}:
                consider(round(t0 + 0.1 * i, 1), tau0 + 2.0 * j, lag)
    assert best_p is not None
    return Heating(best_p[1], best_p[2], len(found), math.sqrt(best_p[0]), best_p[3])


def plan(p: Params, h: Heating, now: float, temp_now: float, minimum: float, forecast, last_outside: float | None, horizon_h: float = HORIZON_H) -> dict:
    """Heat runs that keep the room at or above its minimum for the next HORIZON_H, each as late as is safe and just long enough to
    reach the end of the horizon (or, if one run cannot, as long as is worth it). Returns {'runs': [...], 'curve': the temperature
    with the runs, 30-minute points}."""
    steps = int(horizon_h * 3600 // STEP)
    outs = outside_path(last_outside, now, forecast, steps)
    if any(o is None for o in outs):
        return {"error": "no outside temperature to plan with"}
    lead_steps = -(-LEAD_S // STEP)
    longest = max(RUN_STEP_MIN, round(3 * h.tau_min / RUN_STEP_MIN) * RUN_STEP_MIN)  # after 3 time constants the curve is 95% done

    def after_call(t_call: float, call: int, minutes: float) -> tuple[list[float], list[float]]:
        """(the room while the heat arrives, the room cooling from there to the end of the horizon), one point per STEP after the call."""
        arriving = heat_path(h, t_call, minutes)[: steps - call]
        rest = steps - call - len(arriving)
        return arriving, (simulate(p, arriving[-1], outs[call + len(arriving):]) if rest > 0 else [])

    temps = [temp_now]  # temps[i] = temperature i steps after now
    found: list[dict] = []
    idx, t = 0, temp_now
    for _ in range(MAX_RUNS):
        path = simulate(p, t, outs[idx:])
        k = steps_to_reach(path, minimum)
        if k is None:
            temps.extend(path)
            break
        call = max(idx, idx + k - lead_steps)
        # The heat takes time to arrive (the radiator's lag), so the latest safe call is the latest one after which the room does not
        # reach the minimum before the heat has overtaken the cooling; test it with the longest dose, which heats the most.
        while call > idx and min(after_call(path[call - idx - 1], call, longest)[0]) <= minimum:
            call -= 1
        temps.extend(path[: call - idx])
        t_call = temps[call] if call < len(temps) else t
        chosen = None
        for m in range(RUN_STEP_MIN, longest + 1, RUN_STEP_MIN):
            arriving, tail = after_call(t_call, call, m)
            hold = steps_to_reach(tail, minimum)
            chosen = (m, arriving, tail, hold)
            if hold is None and min(arriving) > minimum:
                break
        m, arriving, tail, hold = chosen
        end = call + len(arriving)
        on_time = call == max(idx, idx + k - lead_steps)
        found.append({"call_by": max(round(now + idx * STEP), round(now + (idx + k) * STEP - LEAD_S)) if on_time else round(now + call * STEP),
                      "minutes": m, "lifts_to": round(t_call + heat_lift(h, t_call, m), 2),
                      "holds_until": None if hold is None else round(now + (end + hold) * STEP)})
        temps.extend(arriving)
        idx, t = end, arriving[-1]
        if hold is None:
            temps.extend(tail)
            break
    else:
        pass
    temps = temps[: steps + 1]
    per = CURVE_STEP_S // STEP
    return {"runs": found, "curve": [[round(now + i * STEP), round(v, 2)] for i, v in enumerate(temps) if i % per == 0]}
