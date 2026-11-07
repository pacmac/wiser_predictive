"""heat_needed: the margin rule over the chosen rooms, and the stage 1 announcement (docs/SPEC.md, MODEL and STAGE 1)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import model
from .const import CONF_ANNOUNCE_DATA, CONF_ANNOUNCE_SCRIPT, CONF_ROOMS, CONF_TRIGGER, DEFAULT_TRIGGER
from .sensor import device_info, room_label


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([HeatNeeded(hass, entry)])


class HeatNeeded(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Heat needed"
    _attr_is_on = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        cfg = {**entry.data, **entry.options}
        self._rooms: list[str] = list(cfg.get(CONF_ROOMS, []))
        self._trigger = float(cfg.get(CONF_TRIGGER, DEFAULT_TRIGGER))
        self._script: str | None = cfg.get(CONF_ANNOUNCE_SCRIPT) or None
        data = cfg.get(CONF_ANNOUNCE_DATA)
        self._data: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
        self._on: dict[str, bool | None] = {}
        self._margin: dict[str, float | None] = {}
        self._memory = model.MinimumMemory()
        self._attr_unique_id = f"{entry.entry_id}_heat_needed"
        self._attr_device_info = device_info(hass, entry)
        self._attr_extra_state_attributes = {"rooms": {}, "rooms_on": []}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_track_state_change_event(self.hass, self._rooms, self._on_change))
        self._evaluate()  # at start-up nothing is announced

    @callback
    def _on_change(self, event) -> None:
        before = dict(self._on)
        self._evaluate()
        # Announce only a room that was known to be off and is now on. unknown -> on stays silent, so a restart of
        # Home Assistant or of the Wiser integration does not announce a room that was already low.
        for room in self._rooms:
            if self._on.get(room) and before.get(room) is False:
                self._announce(room)
        self.async_write_ha_state()

    def _evaluate(self) -> None:
        for room in self._rooms:
            state = self.hass.states.get(room)
            attrs = None if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else state.attributes
            margin = None if attrs is None else self._memory.margin(room, attrs)[0]
            self._margin[room] = margin
            self._on[room] = (
                None if attrs is None else model.room_decision(attrs, bool(self._on.get(room)), self._trigger, margin)
            )
        self._attr_is_on = model.any_room_on(self._on.values())
        self._attr_extra_state_attributes = {
            "rooms": {r: {"margin": self._margin.get(r), "heat_needed": self._on.get(r)} for r in self._rooms},
            "rooms_on": [r for r in self._rooms if self._on.get(r)],
        }

    def _announce(self, room: str) -> None:
        margin = self._margin.get(room)
        if not self._script or margin is None:
            return
        variables = {**self._data, "message": model.announcement(room_label(self.hass, room), margin)}
        self.hass.async_create_task(
            self.hass.services.async_call("script", "turn_on", {"entity_id": self._script, "variables": variables})
        )
