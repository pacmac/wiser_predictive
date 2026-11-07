#!/usr/bin/env python3
"""Development tool: run recorded room history through model.py and measure how good its predictions were.

  replay.py --archive DIR [--outside FILE] [--room NAME]
      DIR     folder of predictive-*.json archives (rooms, outside, boiler). Merged, de-duplicated.
      FILE    outside temperature as JSON [[ms, degrees C], ...]; default is the "outside" series in the archive.
  replay.py --fetch ENTITY --days N --out FILE
      Read-only: pull one sensor's history from the HA box into FILE. Needs HA_SSH, e.g. HA_SSH="ssh root@homeassistant.local".

For every time a room touched its minimum, it asks the model, R minutes beforehand, how long it thought was left, and
compares that with the truth (R). Positive error = the model said later than it was = it would have fired too late.
It also measures boost heat-up: minutes from a boost starting until the reading is 0.3 C higher.
"""
import argparse
import glob
import importlib.util
import json
import os
import pathlib
import shlex
import statistics
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
MS_PER_MIN = 60_000.0
HEATUP_RISE = 0.3  # degrees C: Peter's measure of a boost having worked (task notes 2026-11-06)
WINDOWS = (90, 120, 180)  # minutes; NOT DERIVED: 90 is the old spec's floor. Belongs to the shelved time-to-minimum path.
HORIZONS = (30, 60, 90, 120)  # minutes before the touch at which the model is asked
REARM = 0.2  # degrees C above the minimum before another touch counts: two sensor steps, so a one-step flicker does not
MARGIN_WITHIN = 180  # minutes: a fire counts as warning of a touch only if one follows inside this. Derived: hits at 60/120/180/240/360 min
# were 3/8/9/9/11; 180 is where the curve flattens, and the 2 extra hits at 360 are touches 5 h later, not warning.
OFFSETS = (0.1, 0.2, 0.3, 0.4)  # degrees C above the minimum for the margin rule
SAMPLE_STEP = 5  # minutes between samples. NOT DERIVED (lounge readings: median gap 1.5 min, p90 10.7 min). Shelved time-to-minimum path.


def _load_model():
    path = ROOT / "custom_components" / "wiser_predictive" / "model.py"
    spec = importlib.util.spec_from_file_location("wiser_predictive_model", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wiser_predictive_model"] = mod
    spec.loader.exec_module(mod)
    return mod


model = _load_model()


# --- pure functions on rows [ms, temp, minimum, boosted] --------------------------------------

def touches(rows, offset=0.0):
    """Minutes at which a room reached its minimum (plus `offset`) from above.

    A boost or a change of the minimum starts afresh (a raised target is not the room cooling). After a touch the
    reading must rise REARM above the level before another counts: the sensor steps 0.1 C, so a one-step flicker
    is the same touch.
    """
    out, armed, previous_minimum = [], False, None
    for ts, temp, minimum, boosted in rows:
        level = round(minimum + offset, 2)
        if boosted or minimum != previous_minimum:
            armed = (not boosted) and temp > level
            previous_minimum = minimum
            continue
        if armed and temp <= level:
            out.append(ts / MS_PER_MIN)
            armed = False
        elif temp >= round(level + REARM, 2):
            armed = True
    return out


def margin_rule(rows, offset, within=MARGIN_WITHIN):
    """Fire when the reading comes down to minimum + offset. Returns (leads, false_alarms): minutes of warning before
    the next real touch, for fires followed by a touch within `within` minutes, and the number that were not."""
    real = touches(rows)
    leads, false_alarms = [], 0
    for fire in touches(rows, offset):
        nxt = [t for t in real if fire <= t <= fire + within]
        if nxt:
            leads.append(nxt[0] - fire)
        else:
            false_alarms += 1
    return leads, false_alarms


def resample(rows, start, now, step=SAMPLE_STEP):
    """[(minute, degrees C)] every `step` minutes from `start` to `now`, holding the last reading between changes.

    The Wiser sensor records changes only, so a quiet room has few points and a plain fit over them would measure
    the gap between changes, not the room.
    """
    out, i, held = [], 0, None
    g = start
    while g <= now:
        while i < len(rows) and rows[i][0] / MS_PER_MIN <= g:
            held = rows[i][1]
            i += 1
        if held is not None:
            out.append((g, held))
        g += step
    return out


def heatups(rows, rise=HEATUP_RISE):
    """Minutes from each boost starting until the reading is `rise` above where it was before the boost.

    The search runs past the end of the boost flag (a slow boost gets there after the flag has dropped) and stops at
    the next boost, or when the reading falls back below where it started (the boost did not work).
    """
    out = []
    for i, row in enumerate(rows):
        if not row[3] or (i > 0 and rows[i - 1][3]):
            continue
        base = rows[i - 1][1] if i > 0 else row[1]
        target = round(base + rise, 2) - 1e-9
        flag_dropped = False
        for later in rows[i:]:
            if later[3] and flag_dropped:
                break
            flag_dropped = flag_dropped or not later[3]
            if later[1] < base - 1e-9:
                break
            if later[1] >= target:
                out.append((later[0] - row[0]) / MS_PER_MIN)
                break
    return out


# --- loading ----------------------------------------------------------------------------------

def load_archive(folder):
    rooms, outside = {}, {}
    for path in sorted(glob.glob(os.path.join(folder, "predictive-*.json"))):
        data = json.load(open(path))
        for name, rows in data["rooms"].items():
            rooms.setdefault(name, {}).update({r[0]: r for r in rows})
        outside.update({p[0]: p for p in data["outside"]})
    return (
        {n: sorted(d.values()) for n, d in rooms.items()},
        sorted(outside.values()),
    )


def mean_outside(series, start, end):
    """Mean outside temperature over [start, end] minutes; the last earlier reading if none fall inside."""
    inside = [v for ms, v in series if start <= ms / MS_PER_MIN <= end]
    if inside:
        return sum(inside) / len(inside)
    earlier = [v for ms, v in series if ms / MS_PER_MIN < start]
    return earlier[-1] if earlier else None


# --- the replay -------------------------------------------------------------------------------

def predictions(rows, outside, touch, minimum, window, horizon):
    """(linear, newton) Predictions made `horizon` minutes before `touch`; None when the window held a boost."""
    now = touch - horizon
    span = [r for r in rows if now - window <= r[0] / MS_PER_MIN <= now]
    if any(r[3] for r in span):
        return None
    pts = resample(rows, now - window, now)
    lin = model.predict_linear(pts, minimum)
    to = mean_outside(outside, now - window, now)
    new = model.predict_newton(pts, minimum, to) if to is not None else model.Prediction(None, "no_outside")
    return lin, new


def replay_room(rows, outside):
    results = {}  # (model, window, horizon) -> {"err": [...], "reasons": {reason: n}}
    touch_list = touches(rows)
    by_time = {r[0] / MS_PER_MIN: r for r in rows}
    for touch in touch_list:
        minimum = by_time[touch][2]
        for window in WINDOWS:
            for horizon in HORIZONS:
                pair = predictions(rows, outside, touch, minimum, window, horizon)
                if pair is None:
                    continue
                for name, p in zip(("linear", "newton"), pair):
                    cell = results.setdefault((name, window, horizon), {"err": [], "reasons": {}})
                    if p.minutes is None:
                        cell["reasons"][p.reason] = cell["reasons"].get(p.reason, 0) + 1
                    else:
                        cell["err"].append(p.minutes - horizon)
    return touch_list, results


def report_margin(rows):
    print(f"margin rule (fire at minimum + offset; hit = a real touch within {MARGIN_WITHIN} min; lead in minutes)")
    for offset in OFFSETS:
        leads, false_alarms = margin_rule(rows, offset)
        fires = len(leads) + false_alarms
        lead = f"lead min={min(leads):.0f} median={statistics.median(leads):.0f} max={max(leads):.0f}" if leads else "no hits"
        print(f"  +{offset:.1f} C: {fires} fires, {len(leads)} hits, {false_alarms} false alarms; {lead}")


def pct(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


def report(room, rows, outside):
    touch_list, results = replay_room(rows, outside)
    ups = heatups(rows)
    print(f"\n=== {room}: {len(rows)} readings, {len(touch_list)} touches of the minimum")
    if ups:
        print(f"boost heat-up (+{HEATUP_RISE} C): n={len(ups)} min={min(ups):.0f} median={statistics.median(ups):.0f} max={max(ups):.0f} minutes")
    report_margin(rows)
    print(f"{'model':7}{'window':>7}{'ahead':>7}{'n':>4}{'unknown':>9}{'med err':>9}{'p90 err':>9}{'max late':>10}{'max early':>11}   (minutes; late = said later than truth)")
    for (name, window, horizon), cell in sorted(results.items()):
        e = cell["err"]
        unknown = sum(cell["reasons"].values())
        if e:
            print(f"{name:7}{window:>7}{horizon:>7}{len(e):>4}{unknown:>9}{statistics.median(e):>9.0f}{pct(e, 90):>9.0f}{max(e):>10.0f}{min(e):>11.0f}")
        else:
            print(f"{name:7}{window:>7}{horizon:>7}{0:>4}{unknown:>9}   {cell['reasons']}")


# --- fetching ---------------------------------------------------------------------------------

REMOTE = '''
import json, os, urllib.request, datetime
t = os.environ["SUPERVISOR_TOKEN"]
start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=%(days)s)).strftime("%%Y-%%m-%%dT%%H:%%M:%%S") + "%%2B00:00"
u = "http://supervisor/core/api/history/period/" + start + "?filter_entity_id=%(entity)s&minimal_response&no_attributes"
data = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "Bearer " + t})))
out = []
for row in (data[0] if data else []):
    try:
        v = float(row["state"])
    except ValueError:
        continue
    ts = row.get("last_changed") or row.get("last_updated")
    out.append([datetime.datetime.fromisoformat(ts).timestamp() * 1000, v])
print(json.dumps(out))
'''


def fetch(entity, days, out):
    ssh = os.environ.get("HA_SSH")
    if not ssh:
        sys.exit('set HA_SSH to the command that runs a shell command on your HA box, e.g. HA_SSH="ssh root@homeassistant.local"')
    code = REMOTE % {"days": int(days), "entity": entity}
    done = subprocess.run(shlex.split(ssh) + ["python3 -"], input=code.encode(), capture_output=True, check=True)
    series = json.loads(done.stdout)
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(series, open(out, "w"))
    print(f"{entity}: {len(series)} readings -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive")
    ap.add_argument("--outside")
    ap.add_argument("--room", action="append")
    ap.add_argument("--fetch")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.fetch:
        if not args.out:
            sys.exit("--fetch needs --out FILE")
        return fetch(args.fetch, args.days, args.out)
    if not args.archive:
        sys.exit("need --archive DIR (or --fetch)")
    rooms, forecast = load_archive(args.archive)
    outside = json.load(open(args.outside)) if args.outside else forecast
    print(f"outside series: {args.outside or 'archive forecast'}, {len(outside)} readings")
    for name in args.room or sorted(rooms):
        report(name, rooms[name], outside)


if __name__ == "__main__":
    main()
