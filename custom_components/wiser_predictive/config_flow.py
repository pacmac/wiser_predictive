"""Config flow: select the Wiser hub (skipped when there is only one), then the rooms, the outside sensor, the trigger
margin and the optional announcement. Rooms are discovered from the selected hub. Editable later through the options
flow (the hub is fixed)."""
from __future__ import annotations

from typing import Any, Mapping

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from . import hub as hubs
from . import model
from .const import (
    CONF_ANNOUNCE_DATA,
    CONF_ANNOUNCE_SCRIPT,
    CONF_GAS_KWH_H,
    CONF_GAS_PRICE,
    CONF_HUB,
    CONF_INDOOR_DAMP,
    CONF_OUTSIDE,
    CONF_ROOMS,
    CONF_TRIGGER,
    CONF_WALL_FACTOR,
    CONF_WEATHER,
    DEFAULT_INDOOR_DAMP,
    DEFAULT_TRIGGER,
    DEFAULT_WALL_FACTOR,
    DOMAIN,
)


def _only_weather(hass: HomeAssistant) -> str | None:
    """The weather entity to suggest without asking: the only one there is (like the hub). None if none or several."""
    found = hass.states.async_entity_ids("weather")
    return found[0] if len(found) == 1 else None


def _schema(rooms: list[str], allowed: list[str], current: Mapping[str, Any], weather_default: str | None = None) -> vol.Schema:
    """`current` holds the values already chosen (empty on first setup)."""
    fields: dict[Any, Any] = {}
    fields[vol.Required(CONF_ROOMS, default=rooms)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="climate", multiple=True, include_entities=allowed)
    )
    # Both optional. The panel draws the outside temperature from the sensor if there is one, else from the weather entity.
    fields[vol.Optional(CONF_WEATHER, description={"suggested_value": current.get(CONF_WEATHER, weather_default)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="weather"))
    )
    fields[vol.Optional(CONF_OUTSIDE, description={"suggested_value": current.get(CONF_OUTSIDE)})] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))
    )
    fields[vol.Required(CONF_TRIGGER, default=current.get(CONF_TRIGGER, DEFAULT_TRIGGER))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.1, unit_of_measurement="°C", mode=selector.NumberSelectorMode.BOX)
    )
    # The estimated dampness of an external wall (humidity.py). Ranges: a wall's temperature factor is 0 to 1 (0.3 is already worse than
    # a single skin of brick, 1 a surface as warm as the room); the room's vapour is at least the outdoor air's (1.0) and 1.5 is far
    # beyond the 1.06-1.14 measured in a sheltered space.
    fields[vol.Required(CONF_WALL_FACTOR, default=current.get(CONF_WALL_FACTOR, DEFAULT_WALL_FACTOR))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=0.3, max=1.0, step=0.01, mode=selector.NumberSelectorMode.BOX)
    )
    fields[vol.Required(CONF_INDOOR_DAMP, default=current.get(CONF_INDOOR_DAMP, DEFAULT_INDOOR_DAMP))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=1.0, max=1.5, step=0.01, mode=selector.NumberSelectorMode.BOX)
    )
    # The cost of a planned run: the boiler's gas at full demand (measure it on the house's own meter) and the gas price per kWh.
    # 0 means not set, and the panel then shows no cost. Ranges: a domestic boiler burns up to a few tens of kWh an hour; a price per kWh is under 1.
    fields[vol.Required(CONF_GAS_KWH_H, default=current.get(CONF_GAS_KWH_H, 0.0))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=0.0, max=60.0, step=0.01, unit_of_measurement="kWh/h", mode=selector.NumberSelectorMode.BOX)
    )
    fields[vol.Required(CONF_GAS_PRICE, default=current.get(CONF_GAS_PRICE, 0.0))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=0.0, max=1.0, step="any", mode=selector.NumberSelectorMode.BOX)
    )
    script = current.get(CONF_ANNOUNCE_SCRIPT)
    fields[vol.Optional(CONF_ANNOUNCE_SCRIPT, description={"suggested_value": script})] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="script")
    )
    fields[vol.Optional(CONF_ANNOUNCE_DATA, description={"suggested_value": current.get(CONF_ANNOUNCE_DATA)})] = (
        selector.ObjectSelector()
    )
    return vol.Schema(fields)


class WiserPredictiveConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _hub: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        available = hubs.hubs(self.hass)
        if not available:
            return self.async_abort(reason="no_wiser")
        only = model.single_hub(list(available))
        if only is not None:
            self._hub = only
            return await self.async_step_rooms()
        if user_input is not None:
            self._hub = user_input[CONF_HUB]
            return await self.async_step_rooms()
        options = [selector.SelectOptionDict(value=k, label=v) for k, v in available.items()]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_HUB): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}
            ),
        )

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._hub is not None
        await self.async_set_unique_id(self._hub)
        self._abort_if_unique_id_configured()
        name = hubs.hub_name(self.hass, self._hub)
        found = hubs.discover_rooms(self.hass, self._hub)
        errors: dict[str, str] = {}
        if not found:
            errors["base"] = "no_rooms"
        elif user_input is not None:
            if not user_input[CONF_ROOMS]:
                errors["base"] = "no_rooms_selected"
            else:
                return self.async_create_entry(
                    title=f"Wiser Predictive ({name})", data={**user_input, CONF_HUB: self._hub}
                )
        return self.async_show_form(
            step_id="rooms",
            data_schema=_schema(found, found, {}, _only_weather(self.hass)),
            errors=errors,
            description_placeholders={"hub": name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PredictiveOptionsFlow()


class PredictiveOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        hub_id = current.get(CONF_HUB)
        allowed = hubs.discover_rooms(self.hass, hub_id) if hub_id else []
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current.get(CONF_ROOMS, []), allowed, current, _only_weather(self.hass)),
            description_placeholders={"hub": hubs.hub_name(self.hass, hub_id) if hub_id else "unknown"},
        )
