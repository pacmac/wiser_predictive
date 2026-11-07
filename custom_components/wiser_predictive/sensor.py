"""Sensors: the lowest margin (headline), a margin per room, the trigger in force and the hub (docs/SPEC.md, ENTITIES)."""
from __future__ import annotations

import inspect

from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import model
from . import hub as hubs
from .const import CONF_HUB, CONF_ROOMS, CONF_TRIGGER, DEFAULT_TRIGGER, DOMAIN


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
        accepts_id = "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
        info.update(model.hub_link(hub_dev.id, hub_dev.identifiers, accepts_id))
    return info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rooms = {**entry.data, **entry.options}.get(CONF_ROOMS, [])
    registry = er.async_get(hass)
    for stale in er.async_entries_for_config_entry(registry, entry.entry_id):
        if stale.unique_id.endswith("_time_to_minimum"):  # placeholder from the first build, removed: it never had a value
            registry.async_remove(stale.entity_id)
    entities: list[SensorEntity] = []
    hub_id = entry.data.get(CONF_HUB)
    if hub_id:
        entities.append(HubSensor(hass, entry, hubs.hub_name(hass, hub_id)))
    entities.append(TriggerSensor(hass, entry))
    entities.append(LowestMarginSensor(hass, entry, rooms))
    for room in rooms:
        entities.append(MarginSensor(hass, entry, room, room_label(hass, room)))
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
        self._memory = model.MinimumMemory()

    def _refresh(self) -> None:
        attrs = self._room_attrs()
        margin, minimum, held = (None, None, False) if attrs is None else self._memory.margin(self._room, attrs)
        self._attr_native_value = margin
        self._attr_available = margin is not None  # a thermostat with no reading is unavailable, not "unknown"
        self._attr_extra_state_attributes = (
            {} if attrs is None
            else {"reading": attrs.get("current_temperature"), "minimum": minimum, "minimum_held_during_boost": held,
                  "room": self._room}
        )


class TriggerSensor(SensorEntity):
    """The trigger margin in force: heat is called when a room is this close to its minimum, or closer."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Trigger margin"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._attr_native_value = float({**entry.data, **entry.options}.get(CONF_TRIGGER, DEFAULT_TRIGGER))
        self._attr_unique_id = f"{entry.entry_id}_trigger_margin"
        self._attr_device_info = device_info(hass, entry)


class LowestMarginSensor(SensorEntity):
    """The headline: how close the nearest room is to its minimum, and which room that is."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Lowest margin"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, rooms: list[str]) -> None:
        self._rooms = list(rooms)
        self._attr_unique_id = f"{entry.entry_id}_lowest_margin"
        self._attr_device_info = device_info(hass, entry)
        self._attr_extra_state_attributes = {}
        self._memory = model.MinimumMemory()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_track_state_change_event(self.hass, self._rooms, self._on_change))
        self._refresh()

    @callback
    def _on_change(self, event) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        margins: dict[str, float | None] = {}
        for room in self._rooms:
            state = self.hass.states.get(room)
            ok = state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            margins[room] = self._memory.margin(room, state.attributes)[0] if ok else None
        low = model.lowest_margin(margins)
        self._attr_native_value = None if low is None else low[1]
        self._attr_extra_state_attributes = {
            "room": None if low is None else room_label(self.hass, low[0]),
            "rooms_without_a_reading": [room_label(self.hass, r) for r, m in margins.items() if m is None],
        }
