"""Pure model. No homeassistant imports, so it is testable without a running HA.

Skeleton: the room minimum and the margin above it. The fit, time_to_minimum, lead and heat_needed
decision are specified in docs/SPEC.md and are not built yet.
"""
from __future__ import annotations

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
