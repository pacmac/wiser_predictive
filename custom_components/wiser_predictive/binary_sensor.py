"""heat_needed. Unknown until the model exists: it must not say 'off' while it cannot know (docs/SPEC.md)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([HeatNeeded(entry)])


class HeatNeeded(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Heat needed"
    _attr_is_on = None
    _attr_extra_state_attributes = {"model": "not built yet"}

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_heat_needed"
        self._attr_device_info = device_info(entry)
