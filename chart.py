#!/usr/bin/env python3
"""Development tool: draw a room's recorded history as one page, for looking at (docs/SPEC.md, VISUALISATION).

  chart.py [--room lounge] [--data data] [--out data/chart.html]

Reads what replay.py --fetch saved into data/ (see FILES below) and the hourly forecast in data/forecast_hourly.json.
Panels share one time axis, from the past to 24 h ahead, with a "now" line:
  1 temperature (room, each valve sensor, setpoint)   2 outside (measured, forecast)
  3 rate of change, C per hour (room and outside)      4 heating demand, %
Boosts and heating spans are shaded across all panels. Hover shows every value at that time.
The model's prediction and decision trace are added on top of these in the next stage; this page is the data they stand on.
"""
import argparse
import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

# climate attribute order saved by replay.py --fetch --attrs (see the README line in the handover)
ATTRS = ["current_temperature", "temperature", "target_temp_low", "percentage_demand", "is_heating", "is_boosted",
         "is_override", "is_calling_for_heat", "current_schedule_temp"]
HORIZON_H = 24  # hours of forecast drawn ahead of now (SPEC: past 3 days to 24 h ahead)
GRID = 600  # seconds between samples when working out a rate: 10 min, finer than the 0.1 C sensor steps resolve anyway
RATE_WINDOW = 7200  # seconds. Slope of the last 2 h: the sensors step 0.1 C, so a rate over a window W is quantised to
# 0.1/W per hour = 0.05 C/h for 2 h, against cooling rates of 0.1-0.35 C/h seen in the lounge; 1 h would quantise at 0.1 C/h.


def load(path):
    p = pathlib.Path(path)
    return json.load(open(p)) if p.exists() else []


def column(rows, i):
    """[(seconds, value)] for column i of a fetched attribute series, skipping missing values."""
    # sorted: the history API puts the state at the start of the period first, with the time it last changed (earlier)
    return sorted((r[0] / 1000.0, r[i]) for r in rows if r[i] is not None)


def state_series(rows):
    return sorted((r[0] / 1000.0, r[1]) for r in rows if r[1] is not None)


def hold(points, grid):
    """Value of a step series at each grid time: the last reading at or before it."""
    out, i, held = [], 0, None
    for g in grid:
        while i < len(points) and points[i][0] <= g:
            held = points[i][1]
            i += 1
        out.append(held)
    return out


def interpolate(points, grid):
    """Linear value of a series at each grid time (for the hourly forecast)."""
    out, j = [], 0
    for g in grid:
        while j + 1 < len(points) and points[j + 1][0] <= g:
            j += 1
        if g < points[0][0] or g > points[-1][0]:
            out.append(None)
        elif j + 1 >= len(points):
            out.append(points[-1][1])
        else:
            (t0, v0), (t1, v1) = points[j], points[j + 1]
            out.append(v0 + (v1 - v0) * (g - t0) / (t1 - t0))
    return out


def slope_per_hour(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    return None if sxx == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx * 3600.0


def rates(grid, values, window=RATE_WINDOW):
    """[(seconds, C per hour)]: least-squares slope of the values in the trailing window. Needs 3 points."""
    out = []
    per = window // GRID + 1
    for k, g in enumerate(grid):
        pts = [(grid[m], values[m]) for m in range(max(0, k - per + 1), k + 1) if values[m] is not None]
        if len(pts) >= 3:
            s = slope_per_hour([p[0] for p in pts], [p[1] for p in pts])
            if s is not None:
                out.append((g, round(s, 3)))
    return out


def spans(points):
    """[(start, end)] where a boolean-ish series is true. points are (seconds, value); the last span ends at the last point."""
    out, start = [], None
    for t, v in points:
        if v and start is None:
            start = t
        elif not v and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, points[-1][0]))
    return out


def build(room, data):
    d = pathlib.Path(data)
    climate = load(d / f"climate.wiser_{room}.json")
    if not climate:
        raise SystemExit(f"no {d}/climate.wiser_{room}.json: fetch it with replay.py --fetch climate.wiser_{room} --attrs ...")
    col = {name: i + 1 for i, name in enumerate(ATTRS)}
    reading = column(climate, col["current_temperature"])
    now = max(t for t, _ in reading)
    outside = state_series(load(d / "sensor.stats_outside_temperature.json"))
    itrvs = {  # the valve-mounted sensors the room reading is made from, e.g. "Lounge 1"
        "iTRV " + p.name.split("_itrv_")[1].split("_wiser")[0].replace("_", " ").title(): state_series(load(p))
        for p in sorted(d.glob(f"sensor.wiser_itrv_{room}_*_wiser_lts_temperature_itrv_{room}.json"))
    }
    fc = load(d / "forecast_hourly.json")
    forecast = []
    if fc:
        for f in fc["service_response"][next(iter(fc["service_response"]))]["forecast"]:
            t = datetime.datetime.fromisoformat(f["datetime"]).timestamp()
            if t >= now - 3600:
                forecast.append((t, f["temperature"]))
    start = min(t for t, _ in reading)
    end = now + HORIZON_H * 3600
    grid = [start + k * GRID for k in range(int((end - start) // GRID) + 1)]
    room_hold = hold(reading, [g for g in grid if g <= now])
    room_rate = rates([g for g in grid if g <= now], room_hold)
    out_hold = hold(outside, [g for g in grid if g <= now])
    fut = [g for g in grid if g > now]
    out_future = interpolate(forecast, fut) if forecast else [None] * len(fut)
    out_grid = [g for g in grid if g <= now] + fut
    out_rate = rates(out_grid, out_hold + out_future)
    heating = column(climate, col["is_heating"])
    boosted = column(climate, col["is_boosted"])
    return {
        "room": room, "now": now, "start": start, "end": end,
        "reading": [[round(t), v] for t, v in reading],
        "setpoint": [[round(t), v] for t, v in column(climate, col["temperature"])],
        "itrv": {k: [[round(t), v] for t, v in s] for k, s in itrvs.items()},
        "outside": [[round(t), v] for t, v in outside],
        "forecast": [[round(t), v] for t, v in forecast],
        "room_rate": [[round(t), v] for t, v in room_rate],
        "outside_rate": [[round(t), v] for t, v in out_rate],
        "demand": [[round(t), v] for t, v in column(climate, col["percentage_demand"])],
        "heating": [[round(a), round(b)] for a, b in spans(heating)],
        "boost": [[round(a), round(b)] for a, b in spans(boosted)],
        "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--room", default="lounge")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "data" / "chart.html"))
    args = ap.parse_args()
    payload = build(args.room, args.data)
    html = (ROOT / "chart_template.html").read_text().replace("/*DATA*/null", json.dumps(payload, separators=(",", ":")))
    pathlib.Path(args.out).write_text('<meta charset="utf-8">\n' + html)
    print(f"{args.room}: {len(payload['reading'])} readings, now={datetime.datetime.fromtimestamp(payload['now'], datetime.timezone.utc):%m-%d %H:%M} UTC -> {args.out}")


if __name__ == "__main__":
    main()
