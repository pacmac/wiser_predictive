"""Pure: how damp the inside of an external wall is estimated to be, from the room's temperature and the outdoor air.
No homeassistant imports, so it runs in tests and in chart.py. Times are seconds since the epoch; temperatures are degrees C;
humidity is percent; water activity is a fraction (surface relative humidity / 100).

Why this and not a temperature: Approved Document F 2021 (Volume 1, Appendix B, B10, Table B2) says the moisture criteria for
any dwelling are likely to be met if the moving-average water activity of the internal surfaces of external walls stays below
0.75 over a month, 0.85 over a week and 0.95 over a day, in the colder months. A room temperature is only the means; the
quantity that matters is the wall surface's dampness, which no sensor in a house like this measures, so it is estimated:

  indoor vapour pressure   = k x the outdoor vapour pressure         (an empty, ventilated house takes the outdoor air's water)
  wall surface temperature = T_out + f x (T_in - T_out)              (f: the wall's temperature factor)
  water activity          = indoor vapour pressure / saturation pressure at the wall surface temperature

It is an ESTIMATE and a lower bound on dampness (docs/SPEC.md, STAGE 3 DESIGN: step 5 found a sheltered space here is 6-14% above
the outdoor vapour pressure; damp fabric adds more). The panel says so.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

# Magnus constants for saturation vapour pressure over water (Alduchov and Eskridge 1996; the WMO-recommended form), hPa and C.
_A, _B, _C = 6.112, 17.62, 243.12

# Approved Document F 2021, Volume 1, Table B2: (name, water activity that must not be exceeded by the moving average, hours averaged).
LIMITS = (("day", 0.95, 24), ("week", 0.85, 168), ("month", 0.75, 720))

# f = 1 - Rsi x U with the standard inside-surface resistance Rsi = 0.13 m2K/W (BS EN ISO 6946) and U = 2.1 W/m2K, an uninsulated
# solid brick wall, the worst plain wall (a better wall has a higher f and a drier surface). 1 - 0.13 x 2.1 = 0.727.
DEFAULT_WALL_FACTOR = 0.73
# k: indoor over outdoor vapour pressure. The median over 250 hours of the two garage sensors against the weather was 1.14 (Garage
# Ambient) and 1.06 (Plant Dryer): a sheltered, unheated space is 6-14% damper than outdoors. The larger is taken so the estimate errs
# on the cautious side. Nothing measures a heated room here (docs/SPEC.md, STEP 5 RESULT).
DEFAULT_INDOOR_DAMP = 1.14

HOUR = 3600.0
MAX_GAP_S = 3 * HOUR  # a weather row is written about once an hour (263 rows in 10.9 days), so 3 hours is 3 missed updates: a gap, not a value
SOLVE_STEPS = 20  # bisection on a 40 K range: 40 / 2^20 = 0.00004 K, far finer than the 0.1 K of the room sensor
HOTTEST_C = 40.0  # a room is never heated to this: the search ceiling, and the answer when no lower temperature meets the limit


def sat_pressure(t: float) -> float:
    """Saturation vapour pressure of water at temperature t, hPa."""
    return _A * math.exp(_B * t / (_C + t))


def vapour_pressure(t: float, rh: float) -> float:
    """Vapour pressure of air at temperature t and relative humidity rh (percent), hPa."""
    return sat_pressure(t) * rh / 100.0


def dew_point(t: float, rh: float) -> float | None:
    """Dew point of air at temperature t and relative humidity rh (percent), C. None if the humidity is zero or not given."""
    if rh is None or rh <= 0:
        return None
    g = math.log(rh / 100.0) + _B * t / (_C + t)
    return _C * g / (_B - g)


def surface_temperature(t_in: float, t_out: float, f: float) -> float:
    return t_out + f * (t_in - t_out)


def activity(t_in: float, t_out: float, e_out: float, k: float, f: float) -> float:
    """Estimated water activity of the wall's inside surface. e_out is the outdoor vapour pressure (hPa)."""
    return k * e_out / sat_pressure(surface_temperature(t_in, t_out, f))


def room_rh(t_in: float, e_out: float, k: float) -> float:
    """Estimated relative humidity of the room's air, percent."""
    return 100.0 * k * e_out / sat_pressure(t_in)


def floor(t_out: float, e_out: float, limit: float, k: float, f: float) -> float:
    """The lowest room temperature at which the wall's water activity is at or below `limit`, with the outdoor air as given.
    Never below the outdoor temperature (a room is not colder than outside here); HOTTEST_C if no temperature meets it."""
    if activity(HOTTEST_C, t_out, e_out, k, f) > limit:
        return HOTTEST_C
    lo, hi = t_out, HOTTEST_C
    if activity(lo, t_out, e_out, k, f) <= limit:
        return t_out
    for _ in range(SOLVE_STEPS):  # activity falls as the room warms, so the answer is bracketed
        mid = (lo + hi) / 2.0
        if activity(mid, t_out, e_out, k, f) > limit:
            lo = mid
        else:
            hi = mid
    return hi


def hourly_weather(rows: Iterable[tuple[float, float, float]], until: float | None = None) -> list[tuple[float, float, float]]:
    """[(hour start, temperature, humidity)], one per hour, from (seconds, temperature, humidity) rows in any order: each hour
    takes the latest row at or before its start, unless that row is older than MAX_GAP_S (then the hour is left out). `until`
    carries the last row forward to that time (the panel's now); without it the hours stop at the last row, which is what the
    archive wants: only hours the weather entity actually reported."""
    rows = sorted(r for r in rows if r[1] is not None and r[2] is not None)
    if not rows:
        return []
    out, i = [], 0
    h = math.floor(rows[0][0] / HOUR) * HOUR
    last = rows[-1][0] if until is None else max(rows[-1][0], until)
    while h <= last:
        while i + 1 < len(rows) and rows[i + 1][0] <= h:
            i += 1
        t, temp, rh = rows[i]
        if t <= h and h - t <= MAX_GAP_S:
            out.append((h, float(temp), float(rh)))
        h += HOUR
    return out


def _at(points: Sequence[tuple[float, float]], t: float, within: float) -> float | None:
    """The latest value at or before t, if it is no older than `within` seconds (a step, like a sensor reading)."""
    best = None
    for pt, v in points:
        if pt <= t:
            best = (pt, v)
        else:
            break
    return None if best is None or t - best[0] > within else best[1]


def _along(curve: Sequence[Sequence[float]], t: float) -> float | None:
    """Linear interpolation on a [[t, value]] curve, None outside it."""
    if not curve or t < curve[0][0] or t > curve[-1][0]:
        return None
    for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
        if t0 <= t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return curve[-1][1]


PLAN_LIMIT = "week"  # the limit the heating plan is held to, see moisture_floor
FORECAST_HOURS = 48  # the span of the hourly forecast the floor rests on: the forecast's own length


def moisture_floor(weather: Sequence[tuple[float, float, float]], now: float, k: float = DEFAULT_INDOOR_DAMP,
                   f: float = DEFAULT_WALL_FACTOR, limit_name: str = PLAN_LIMIT) -> float | None:
    """The room temperature (C) below which the estimated wall dampness would pass the `limit_name` limit if the forecast's mean
    weather lasted; None with no forecast. The heating plan holds the room above the larger of this and its own minimum.
    PLAN_LIMIT is the weekly 0.85: the day limit (0.95) is almost never binding (10 Nov: 6.8 C against the 12.5 C minimum), and the
    month limit (0.75) asks 13.6-15.0 C in mild wet weather, which an empty house cannot afford continuously; the month average is
    drawn on the panel against its limit so it is watched, not held. The week is the middle of the three, and one constant to change."""
    span = [w for w in weather if now < w[0] <= now + FORECAST_HOURS * HOUR]
    if not span:
        return None
    limit = next(lim for name, lim, _ in LIMITS if name == limit_name)
    t_mean = sum(w[1] for w in span) / len(span)
    e_mean = sum(vapour_pressure(w[1], w[2]) for w in span) / len(span)
    return round(floor(t_mean, e_mean, limit, k, f), 2)


def chart_block(
    reading: Sequence[tuple[float, float]],
    weather: Sequence[tuple[float, float, float]],
    now: float,
    k: float = DEFAULT_INDOOR_DAMP,
    f: float = DEFAULT_WALL_FACTOR,
    curve: Sequence[Sequence[float]] | None = None,
    reading_age_s: float = 6 * HOUR,
) -> dict:
    """What the panel draws about dampness for one room.

    reading: [(seconds, room temperature)]; weather: hourly [(hour start, outside temperature, outside humidity)] across the past
    window and the forecast; curve: [[seconds, room temperature]] predicted with no heating (the future hours use it; without it
    they are left out rather than invented). Returns the estimated water activity per hour, the outdoor dew point, the three
    limits, what the room has averaged over the last day, week and month (and how many hours that rests on), and the floor
    the forecast needs."""
    reading = sorted(reading)
    act, dew, rooms = [], [], {}
    for t, temp, rh in weather:
        t_in = _at(reading, t, reading_age_s) if t <= now else _along(curve or [], t)
        d = dew_point(temp, rh)
        if d is not None:
            dew.append([round(t), round(d, 2)])
        if t_in is None:
            continue
        e_out = vapour_pressure(temp, rh)
        act.append([round(t), round(activity(t_in, temp, e_out, k, f), 4)])
        rooms[t] = t_in

    def mean_over(hours: int) -> dict:
        vals = [a for t, a in act if now - hours * HOUR < t <= now]
        return {"value": round(sum(vals) / len(vals), 4) if vals else None, "hours": len(vals), "of": hours}

    past = [w for w in weather if w[0] <= now]
    ahead = [w for w in weather if w[0] > now]
    nowrow = past[-1] if past else None
    block_now = None
    if nowrow and nowrow[0] in rooms:
        t, temp, rh = nowrow
        e = vapour_pressure(temp, rh)
        block_now = {"t": round(t), "activity": round(activity(rooms[t], temp, e, k, f), 4), "room_rh": round(room_rh(rooms[t], e, k), 1),
                     "room_temp": round(rooms[t], 2), "outside": round(temp, 2), "outside_rh": round(rh, 1), "dew": round(dew_point(temp, rh), 2)}
    floors: dict = {}
    nxt = [w for w in ahead if w[0] <= now + 24 * HOUR]
    if nxt:  # the day limit: the warmest the room must be at the worst hour of the next 24
        worst = max(nxt, key=lambda w: floor(w[1], vapour_pressure(w[1], w[2]), LIMITS[0][1], k, f))
        floors["day"] = {"temp": round(floor(worst[1], vapour_pressure(worst[1], worst[2]), LIMITS[0][1], k, f), 2), "at": round(worst[0])}
    span = [w for w in ahead if w[0] <= now + 48 * HOUR]
    if span:  # the week and month limits are averages: what the room would need if the forecast's mean weather lasted
        t_mean = sum(w[1] for w in span) / len(span)
        e_mean = sum(vapour_pressure(w[1], w[2]) for w in span) / len(span)
        for name, limit, _ in LIMITS[1:]:
            floors[name] = {"temp": round(floor(t_mean, e_mean, limit, k, f), 2), "hours": len(span)}
    return {
        "activity": act, "dew": dew, "limits": {name: limit for name, limit, _ in LIMITS},
        "now": block_now, "means": {name: mean_over(h) for name, _, h in LIMITS}, "floor": floors, "k": k, "f": f,
    }


def forecast_rows(rows: Iterable[Mapping]) -> list[tuple[float, float, float]]:
    """A weather entity's hourly forecast ([{'datetime': iso string, 'temperature', 'humidity', ...}]) -> [(seconds, temperature,
    humidity)]. Rows without both values are left out."""
    import datetime

    out = []
    for row in rows:
        try:
            out.append((datetime.datetime.fromisoformat(row["datetime"]).timestamp(), float(row["temperature"]), float(row["humidity"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def shifted(rows: Iterable[tuple[float, float, float]], offset: float) -> list[tuple[float, float, float]]:
    """The same weather with the air `offset` degrees colder (negative) or warmer, carrying the same water: temperature + offset,
    humidity from the unchanged vapour pressure, capped at 100%. For the panel's what-if."""
    out = []
    for t, temp, rh in rows:
        e = vapour_pressure(temp, rh)
        moved = temp + offset
        out.append((t, moved, min(100.0, 100.0 * e / sat_pressure(moved))))
    return out


def join_weather(actual: Sequence[tuple[float, float, float]], forecast: Sequence[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """What happened (hourly), then the forecast for the hours after the last of it."""
    last = actual[-1][0] if actual else None
    return list(actual) + [w for w in sorted(forecast) if last is None or w[0] > last]


def hourly_from_states(states: Iterable[tuple[float, Mapping]], until: float | None = None) -> list[tuple[float, float, float]]:
    """(seconds, attributes) of a weather entity's states -> hourly (hour start, temperature, humidity). Attributes without both are left out."""
    rows = []
    for t, a in states:
        try:
            rows.append((float(t), float(a["temperature"]), float(a["humidity"])))
        except (KeyError, TypeError, ValueError):
            continue
    return hourly_weather(rows, until)
