"""Pure model. No homeassistant imports, so it is testable without a running HA.

Skeleton: the room minimum and the margin above it. The fit, time_to_minimum, lead and heat_needed
decision are specified in docs/SPEC.md and are not built yet.
"""
from __future__ import annotations

from typing import Any, Mapping


def minimum_of(attrs: Mapping[str, Any]) -> float | None:
    """A passive room's minimum is its thermostat LOW; the lounge has one target and that is its minimum."""
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
