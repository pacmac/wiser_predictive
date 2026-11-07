"""Home Assistant side of hub handling. The decisions themselves are in model.py (tested without HA)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from . import model
from .const import WISER


def hubs(hass: HomeAssistant) -> dict[str, str]:
    """Every Wiser hub: config entry id -> display name."""
    return {e.entry_id: hub_name(hass, e.entry_id) for e in hass.config_entries.async_entries(WISER)}


def hub_device(hass: HomeAssistant, hub_id: str) -> DeviceEntry | None:
    """The hub's own device: the one its room devices are connected via."""
    registry = dr.async_get(hass)
    for device in registry.devices.values():
        if hub_id in device.config_entries and device.via_device_id:
            hub = registry.async_get(device.via_device_id)
            if hub is not None:
                return hub
    return None


def hub_name(hass: HomeAssistant, hub_id: str) -> str:
    hub = hub_device(hass, hub_id)
    if hub is not None:
        return hub.name_by_user or hub.name or hub_id
    entry = hass.config_entries.async_get_entry(hub_id)
    return entry.title if entry else hub_id


def discover_rooms(hass: HomeAssistant, hub_id: str) -> list[str]:
    """Rooms (not the hot water channel) of one hub."""
    candidates = []
    for entry in er.async_get(hass).entities.values():
        if entry.platform == WISER and entry.domain == "climate":
            state = hass.states.get(entry.entity_id)
            if state is not None:
                candidates.append((entry.entity_id, entry.config_entry_id, state.attributes))
    return model.rooms_of_hub(candidates, hub_id)
