"""Pure thermal model of one room (no homeassistant imports). Learned from the recorded history, used to predict.

A room with its heating off cools toward an equilibrium that depends on the outside temperature:

    dT/dt = c0 + c1*T + c2*Tout            (c1 < 0)

so the cooling time constant is tau = -1/c1 and the equilibrium is Teq(Tout) = -(c0 + c2*Tout)/c1. The constant c0 is what the
house adds (other rooms, gains); c2 is how strongly the outside pulls. It is fitted by least squares on the history,
using only periods when the room had free cooling (no heating, and not just after it). Times are seconds, temperatures C.
docs/SPEC.md, MODEL. Measured in replay.py --model against "the temperature stays where it is".
"""
from __future__ import annotations

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
    """(T at the start, mean outside over the window, rate C/h) for every window of free cooling.
    The three sequences share one time grid of STEP seconds. A window counts when the heating was off for SETTLE steps before it
    and all through it, and the temperature and outside are known throughout."""
    n = len(temps)
    out: list[tuple[float, float, float]] = []
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
        out.append((temps[i], sum(outs) / len(outs), (temps[end] - temps[i]) / (WINDOW * STEP / 3600.0)))
    return out


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


def predict(p: Params, now: float, temp_now: float, minimum: float, forecast, last_outside: float | None) -> dict:
    """If no heat is supplied from now: the room's curve for the next HORIZON_H, when it reaches the minimum, the latest moment
    to call for heat (LEAD_S earlier), and the lowest point. Needs the outside path (measured now, then the forecast)."""
    steps = int(HORIZON_H * 3600 // STEP)
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
        "minimum": minimum, "curve": curve, "reaches_at": reaches,
        "call_by": None if reaches is None else max(round(now), reaches - LEAD_S),
        "lowest": [round(now + (low_i + 1) * STEP), round(path[low_i], 2)],
        "lead_s": LEAD_S, "tau_h": round(p.tau_h, 1), "windows": p.n,
        "outside_low": min(((t, v) for t, v in forecast if t > now), key=lambda x: x[1], default=None),
    }
