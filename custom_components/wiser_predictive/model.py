"""Pure model. No homeassistant imports, so it is testable without a running HA.

Skeleton: the room minimum and the margin above it. The fit, time_to_minimum, lead and heat_needed
decision are specified in docs/SPEC.md and are not built yet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


def is_room(attrs: Mapping[str, Any]) -> bool:
    """Wiser room thermostats carry is_passive; the hot water channel does not."""
    return "is_passive" in attrs


def rooms_of_hub(candidates: Iterable[tuple[str, str, Mapping[str, Any]]], hub: str) -> list[str]:
    """Entity ids of the rooms on one hub. candidates are (entity_id, hub_id, attributes)."""
    return sorted(entity_id for entity_id, hub_id, attrs in candidates if hub_id == hub and is_room(attrs))


def single_hub(hubs: Sequence[str]) -> str | None:
    """The hub to use without asking, when there is exactly one; None means the user must choose (or there is none)."""
    return hubs[0] if len(hubs) == 1 else None


def room_name(entity_id: str, attrs: Mapping[str, Any]) -> str:
    """The entity's own name ("Bed 3"), else its friendly name, else the entity id made readable."""
    return attrs.get("name") or attrs.get("friendly_name") or entity_id.split(".", 1)[1].replace("_", " ").title()


# --- time to minimum --------------------------------------------------------------------------
# Points are (minutes, degrees C), oldest first. The caller chooses the window with recent().

MIN_SPAN = 90.0  # minutes: docs/SPEC.md, a shorter window is noise at 0.1 C resolution. The replay confirms or changes it.


@dataclass(frozen=True)
class Prediction:
    """minutes is None when it cannot be known; reason says why (shown on the entity, never hidden)."""

    minutes: float | None
    reason: str  # ok | short_window | not_cooling | no_reach


def recent(points: Sequence[tuple[float, float]], now: float, window: float) -> list[tuple[float, float]]:
    return [(t, v) for t, v in points if now - window <= t <= now]


def _regress(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Least squares line through the points: (slope per minute, fitted value at the last point)."""
    n = len(points)
    tm = sum(t for t, _ in points) / n
    vm = sum(v for _, v in points) / n
    sxx = sum((t - tm) ** 2 for t, _ in points)
    slope = sum((t - tm) * (v - vm) for t, v in points) / sxx
    return slope, vm + slope * (points[-1][0] - tm)


def _short(points: Sequence[tuple[float, float]], min_span: float) -> bool:
    return len(points) < 2 or points[-1][0] - points[0][0] < min_span


def predict_linear(points: Sequence[tuple[float, float]], minimum: float, min_span: float = MIN_SPAN) -> Prediction:
    """Straight-line fit. Minutes until the fitted line reaches the minimum."""
    if _short(points, min_span):
        return Prediction(None, "short_window")
    slope, now_value = _regress(points)
    if now_value <= minimum:
        return Prediction(0.0, "ok")
    if slope >= 0:
        return Prediction(None, "not_cooling")
    return Prediction((now_value - minimum) / -slope, "ok")


def predict_newton(
    points: Sequence[tuple[float, float]], minimum: float, outside: float, min_span: float = MIN_SPAN
) -> Prediction:
    """Newton cooling toward a constant outside temperature: ln(T - outside) falls in a straight line."""
    if _short(points, min_span):
        return Prediction(None, "short_window")
    if any(v <= outside for _, v in points):
        return Prediction(None, "not_cooling")
    slope, log_now = _regress([(t, math.log(v - outside)) for t, v in points])
    now_value = outside + math.exp(log_now)
    if now_value <= minimum:
        return Prediction(0.0, "ok")
    if slope >= 0:
        return Prediction(None, "not_cooling")
    if minimum <= outside:
        return Prediction(None, "no_reach")
    return Prediction(math.log((now_value - outside) / (minimum - outside)) / -slope, "ok")


REARM = 0.2  # degrees C: two steps of the 0.1 C sensor, so a one-step flicker cannot flap the decision (matches replay.py)


def heat_needed(margin_c: float | None, was_on: bool, trigger: float) -> bool | None:
    """Margin rule. On at `trigger` degrees above the minimum or lower; off at trigger + REARM or higher; in between it
    keeps its state. None when the margin is unknown, so it never claims 'off' while it cannot know."""
    if margin_c is None:
        return None
    if margin_c <= trigger:
        return True
    if margin_c >= round(trigger + REARM, 2):
        return False
    return was_on


def minimum_of(attrs: Mapping[str, Any]) -> float | None:
    """A passive room's minimum is its thermostat LOW; a non-passive room has one target and that is its minimum."""
    low = attrs.get("target_temp_low")
    if low is not None:
        return float(low)
    target = attrs.get("temperature")
    return float(target) if target is not None else None


def margin(attrs: Mapping[str, Any]) -> float | None:
    """Degrees C the reading is above the minimum; negative below it; None when either is unknown."""
    reading = attrs.get("current_temperature")
    minimum = minimum_of(attrs)
    if reading is None or minimum is None:
        return None
    return round(float(reading) - minimum, 2)
