"""Pure: shape recorded history into what the panel draws. No homeassistant imports, so it runs in tests and in chart.py.

Times are seconds since the epoch. The panel draws: the room's reading, the outside temperature (measured, then the
forecast), and the periods the heating was on (Wiser's own is_heating and is_boosted flags).
"""
from __future__ import annotations

import datetime
from typing import Any, Iterable, Mapping, Sequence

HORIZON_H = 24  # hours of forecast drawn ahead of now (docs/SPEC.md, VISUALISATION: past days to 24 h ahead)


def spans(points: Sequence[tuple[float, Any]]) -> list[tuple[float, float]]:
    """[(start, end)] where a flag was true. points are (seconds, flag) oldest first; a span still open at the last point
    ends there."""
    out: list[tuple[float, float]] = []
    start = None
    for t, v in points:
        if v and start is None:
            start = t
        elif not v and start is not None:
            out.append((start, t))
            start = None
    if start is not None and points:
        out.append((start, points[-1][0]))
    return out


def _pairs(points: Iterable[tuple[float, float]]) -> list[list[float]]:
    return [[round(t), v] for t, v in sorted(points)]


def build(
    name: str,
    climate: Sequence[tuple[float, Mapping[str, Any]]],
    outside: Sequence[tuple[float, float]],
    forecast: Sequence[tuple[float, float]],
    now: float,
    notes: Sequence[str] = (),
    built: str | None = None,
) -> dict[str, Any]:
    """climate is [(seconds, attributes)] of the room's climate entity; outside and forecast are [(seconds, degrees C)]."""
    rows = sorted(climate, key=lambda r: r[0])
    reading = [(t, float(a["current_temperature"])) for t, a in rows if a.get("current_temperature") is not None]
    heating = spans([(t, bool(a.get("is_heating"))) for t, a in rows])
    boost = spans([(t, bool(a.get("is_boosted"))) for t, a in rows])
    return {
        "name": name,
        "now": round(now),
        "end": round(now + HORIZON_H * 3600),
        "reading": _pairs(reading),
        "outside": _pairs(outside),
        "forecast": _pairs((t, v) for t, v in forecast if t >= now - 3600),
        "heating": [[round(a), round(b)] for a, b in heating],
        "boost": [[round(a), round(b)] for a, b in boost],
        "notes": list(notes),
        "built": built or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
    }
