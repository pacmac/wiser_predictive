"""Per-room sensors. margin is real. time_to_minimum is unknown until the model is built (docs/SPEC.md)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import model
from . import hub as hubs
from .const import CONF_HUB, CONF_ROOMS, DOMAIN


def room_label(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return model.room_name(entity_id, state.attributes if state else {})


def device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Wiser Predictive",
        manufacturer="pacmac",
        model="Heating predictor",
        entry_type=DeviceEntryType.SERVICE,
    )
    hub_id = entry.data.get(CONF_HUB)
    hub_dev = hubs.hub_device(hass, hub_id) if hub_id else None
    if hub_dev is not None:
        info["via_device"] = next(iter(hub_dev.identifiers))
    return info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rooms = {**entry.data, **entry.options}.get(CONF_ROOMS, [])
    entities: list[SensorEntity] = []
    hub_id = entry.data.get(CONF_HUB)
    if hub_id:
        entities.append(HubSensor(hass, entry, hubs.hub_name(hass, hub_id)))
    for room in rooms:
        label = room_label(hass, room)
        entities.append(MarginSensor(hass, entry, room, label))
        entities.append(TimeToMinimumSensor(hass, entry, room, label))
    async_add_entities(entities)


class HubSensor(SensorEntity):
    """Shows which Wiser hub this entry was set up for."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Hub"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name: str) -> None:
        self._attr_native_value = name
        self._attr_unique_id = f"{entry.entry_id}_hub"
        self._attr_device_info = device_info(hass, entry)


class _RoomSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, room: str) -> None:
        self._room = room
        self._attr_device_info = device_info(hass, entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_track_state_change_event(self.hass, [self._room], self._on_change))
        self._refresh()

    @callback
    def _on_change(self, event) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _room_attrs(self):
        state = self.hass.states.get(self._room)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.attributes

    def _refresh(self) -> None:
        raise NotImplementedError


class MarginSensor(_RoomSensor):
    """Degrees C the room reading is above its minimum. Negative means below it."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, room: str, label: str) -> None:
        super().__init__(hass, entry, room)
        self._attr_name = f"{label} margin"
        self._attr_unique_id = f"{entry.entry_id}_{room}_margin"
        self._attr_extra_state_attributes = {}

    def _refresh(self) -> None:
        attrs = self._room_attrs()
        self._attr_native_value = None if attrs is None else model.margin(attrs)
        self._attr_extra_state_attributes = (
            {} if attrs is None
            else {"reading": attrs.get("current_temperature"), "minimum": model.minimum_of(attrs), "room": self._room}
        )


class TimeToMinimumSensor(_RoomSensor):
    """Minutes until the room reaches its minimum. Unknown until the model exists; never a made-up value."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_value = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, room: str, label: str) -> None:
        super().__init__(hass, entry, room)
        self._attr_name = f"{label} time to minimum"
        self._attr_unique_id = f"{entry.entry_id}_{room}_time_to_minimum"
        self._attr_extra_state_attributes = {"model": "not built yet", "room": room}

    def _refresh(self) -> None:
        return None
