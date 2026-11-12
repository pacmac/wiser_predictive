#!/usr/bin/env python3
"""Development tool: preview the Home Assistant panel on recorded history, before it is installed (docs/SPEC.md).

  chart.py [--room lounge] [--data data] [--out data/chart.html]

Reads what replay.py --fetch saved into data/ (climate.wiser_<room>.json with --attrs, the outside sensor's history, and
the hourly forecast in forecast_hourly.json), shapes it with the same series.py the integration uses, and writes one page that
runs the same frontend/panel.js the sidebar panel runs, with a stand-in for Home Assistant's `hass`.
"""
import argparse
import datetime
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PKG = ROOT / "custom_components" / "wiser_predictive"

# climate attribute order saved by `replay.py --fetch climate.wiser_<room> --attrs ...`
ATTRS = ["current_temperature", "temperature", "target_temp_low", "percentage_demand", "is_heating", "is_boosted",
         "is_override", "is_calling_for_heat", "current_schedule_temp"]
OUTSIDE_FILE = "sensor.stats_outside_temperature.json"  # this house's outside sensor history; the preview takes it as a given


sys.path.insert(0, str(PKG))  # series.py imports thermal and model as plain modules here
import humidity  # noqa: E402
import series  # noqa: E402


def load(path):
    p = pathlib.Path(path)
    return json.load(open(p)) if p.exists() else []


def climate_rows(rows):
    """[(seconds, attributes)] from rows saved as [ms, attr1, attr2, ...]."""
    return [(r[0] / 1000.0, dict(zip(ATTRS, r[1:]))) for r in rows]


def forecast_rows(fc):
    if not fc:
        return []
    entity = next(iter(fc["service_response"]))
    return [(datetime.datetime.fromisoformat(f["datetime"]).timestamp(), f["temperature"]) for f in fc["service_response"][entity]["forecast"]]


def build(room, data, offset=0.0):
    d = pathlib.Path(data)
    rows = load(d / f"climate.wiser_{room}.json")
    if not rows:
        raise SystemExit(f"no {d}/climate.wiser_{room}.json: fetch it with replay.py --fetch climate.wiser_{room} --attrs {','.join(ATTRS)}")
    climate = climate_rows(rows)
    now = max(t for t, a in climate if a.get("current_temperature") is not None)
    outside = [(r[0] / 1000.0, r[1]) for r in load(d / OUTSIDE_FILE) if r[1] is not None]
    forecast = [(t, v + offset) for t, v in forecast_rows(load(d / "forecast_hourly.json"))]
    latest = max(climate, key=lambda r: r[0])[1]
    low = latest.get("target_temp_low")
    found = series.learn_without_memory(climate, outside, now)  # the preview keeps nothing between runs
    weather = [(r[0] / 1000.0, r[1], r[2]) for r in load(d / "weather_history.json") if r[1] is not None and r[2] is not None]
    fc = load(d / "forecast_hourly.json")
    joined = []
    if weather:  # the same joining the integration does in panel.weather_for: what happened (hourly), then the forecast, with the what-if shift
        ahead = humidity.forecast_rows(fc["service_response"][next(iter(fc["service_response"]))]["forecast"]) if fc else []
        if offset:
            ahead = humidity.shifted(ahead, offset)
        joined = humidity.join_weather(humidity.hourly_weather([w for w in weather if w[0] <= now], until=now), ahead)
    prediction, notes = series.predict(climate, outside, forecast, now, low, bool(latest.get("is_heating") or latest.get("is_boosted")),
                                       None if found is None else found["params"], humidity.moisture_floor(joined, now))
    damp = None
    if joined:
        reading = [(t, float(a["current_temperature"])) for t, a in climate if a.get("current_temperature") is not None]
        damp = humidity.chart_block(reading, joined, now, curve=prediction["curve"] if prediction else None)
    chart = series.build(room.replace("_", " ").title(), climate, outside, forecast, now, notes, prediction=prediction,
                         character=None if found is None else found["character"], learning_info=None if found is None else found["info"],
                         humidity=damp)
    return {"entries": [{"entry_id": "preview", "title": "Preview", "rooms": [{"entity_id": f"climate.wiser_{room}", "name": chart["name"]}]}],
            "entry_id": "preview", "room": f"climate.wiser_{room}", "chart": chart}


def rooms_payload(data):
    """What panel.py's wiser_predictive/rooms returns: each fetched room's thermal character with its uncertainty."""
    from dataclasses import asdict
    import thermal

    d = pathlib.Path(data)
    outside = [(r[0] / 1000.0, r[1]) for r in load(d / OUTSIDE_FILE) if r[1] is not None]
    out = []
    for path in sorted(d.glob("climate.wiser_*.json")):
        name = path.stem.replace("climate.wiser_", "")
        rows = climate_rows(load(path))
        found = series.learn_without_memory(rows, outside, max(t for t, _ in rows))
        out.append({"entity_id": f"climate.wiser_{name}", "name": name.replace("_", " ").title(),
                    "character": None if found is None else found["character"], "learning": None if found is None else found["info"]})
    return {"rooms": out, "notes": []}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--room", default="lounge")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "data" / "chart.html"))
    ap.add_argument("--cold", type=float, default=0.0, help="what-if: degrees colder than the forecast")
    args = ap.parse_args()
    payload = build(args.room, args.data, -args.cold)
    html = (ROOT / "chart_template.html").read_text()
    html = html.replace("/*PANEL*/", (PKG / "frontend" / "panel.js").read_text().replace("</script", "<\\/script"))
    html = html.replace("/*DATA*/null", json.dumps(payload, separators=(",", ":")))
    html = html.replace("/*ROOMS*/null", json.dumps(rooms_payload(args.data), separators=(",", ":")))
    pathlib.Path(args.out).write_text('<meta charset="utf-8">\n' + html)
    c = payload["chart"]
    print(f"{args.room}: {len(c['reading'])} readings, now={datetime.datetime.fromtimestamp(c['now'], datetime.timezone.utc):%m-%d %H:%M} UTC -> {args.out}")


if __name__ == "__main__":
    main()
