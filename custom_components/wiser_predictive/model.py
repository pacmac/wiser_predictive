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

MIN_SPAN = 90.0  # minutes. NOT DERIVED: it came from the old spec. The replay showed these fits are too inaccurate to use, so no entity does.


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


def rearmed(margin_c: float | None, trigger: float) -> bool:
    """A room whose minimum was put up stays quiet until it has climbed to trigger + REARM above the new one (the same
    level at which the margin rule turns a room off), so a step-up of the target is not announced as a cooling room."""
    return margin_c is not None and margin_c >= round(trigger + REARM, 2)


def hub_link(hub_device_id: str | None, hub_identifiers: Iterable[tuple[str, str]], accepts_id: bool) -> dict[str, Any]:
    """Device-registry keyword that connects our device via the Wiser hub. Newer Home Assistant takes via_device_id
    (via_device is deprecated and stops working in 2027.8); older Home Assistant only knows via_device."""
    if hub_device_id is None:
        return {}
    if accepts_id:
        return {"via_device_id": hub_device_id}
    return {"via_device": next(iter(hub_identifiers))}


EPISODE_OVER_FLAGS =("is_heating", "is_boosted", "is_override")  # Wiser's own room flags: heat is already being supplied


_AUTO: Any = object()


def room_decision(attrs: Mapping[str, Any], was_on: bool, trigger: float, margin_c: Any = _AUTO) -> bool | None:
    """heat_needed for one room from its climate attributes: the margin rule, off once heat is being supplied.
    margin_c is the margin to use (MinimumMemory's); by default it is worked out from the attributes."""
    if margin_c is _AUTO:
        margin_c = margin(attrs)
    if attrs.get("current_temperature") is None:
        return None
    if any(attrs.get(flag) for flag in EPISODE_OVER_FLAGS):
        return False  # heat is being supplied, whatever the margin says
    return heat_needed(margin_c, was_on, trigger)


MINIMUM_RAISED_BY = ("is_boosted", "is_override")  # while either is set, a non-passive room's target is the raised one


class MinimumMemory:
    """A room's minimum, kept through a boost.

    A boost or override raises the thermostat's target (lounge: 12.5 -> 20.5), so reading minus target is nonsense while
    it lasts. Passive rooms are not affected (their minimum is the LOW setting). For the others, the last minimum seen
    before the raise is held until it ends; if the raise was already on when this started, there is no minimum to hold
    and the margin is unknown (never a made-up number)."""

    def __init__(self) -> None:
        self._held: dict[str, float] = {}
        self._stepped: set[str] = set()

    def minimum(self, room: str, attrs: Mapping[str, Any]) -> tuple[float | None, bool]:
        """(minimum, held). held is True when the minimum is the remembered pre-boost one."""
        current = minimum_of(attrs)
        raised = attrs.get("target_temp_low") is None and any(attrs.get(f) for f in MINIMUM_RAISED_BY)
        if raised:
            return self._held.get(room), True
        if current is not None:
            previous = self._held.get(room)
            if previous is not None and current > previous + 1e-9:
                self._stepped.add(room)  # the schedule (or a hand) put the minimum UP: the room did not cool
            self._held[room] = current
        return current, False

    def take_step_up(self, room: str) -> bool:
        """True once after the room's minimum was put up (and not by a boost). The replay ignores these too."""
        had = room in self._stepped
        self._stepped.discard(room)
        return had

    def margin(self, room: str, attrs: Mapping[str, Any]) -> tuple[float | None, float | None, bool]:
        """(margin, minimum, held)."""
        minimum, held = self.minimum(room, attrs)
        reading = attrs.get("current_temperature")
        if reading is None or minimum is None:
            return None, minimum, held
        return round(float(reading) - minimum, 2), minimum, held


def any_room_on(states: Iterable[bool | None]) -> bool | None:
    """On if any room is on; off if at least one room is known and none is on; unknown only when none is known."""
    known = [s for s in states if s is not None]
    if not known:
        return None
    return any(known)


def lowest_margin(margins: Mapping[str, float | None]) -> tuple[str, float] | None:
    """(room, margin) of the room closest to, or furthest below, its minimum; None when no room has a margin."""
    known = [(m, r) for r, m in margins.items() if m is not None]
    if not known:
        return None
    m, r = min(known)
    return r, m


def announcement(name: str, margin_c: float) -> str:
    rounded = round(margin_c, 1)
    if rounded == 0:
        return f"{name} is at its minimum"
    return f"{name} is {abs(rounded):.1f} degrees {'above' if rounded > 0 else 'below'} its minimum"


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
