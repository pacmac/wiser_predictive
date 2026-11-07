"""Config flow: rooms are discovered from the Wiser integration, the outside sensor is the user's choice.
Editable later through the options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector

from . import model
from .const import CONF_OUTSIDE, CONF_ROOMS, DOMAIN


def discover_rooms(hass: HomeAssistant) -> list[str]:
    """Climate entities registered by the wiser integration that are rooms (not the hot water channel)."""
    found = []
    for entry in er.async_get(hass).entities.values():
        if entry.platform == "wiser" and entry.domain == "climate":
            state = hass.states.get(entry.entity_id)
            if state is not None and model.is_room(state.attributes):
                found.append(entry.entity_id)
    return sorted(found)


def _schema(rooms: list[str], outside: str | None) -> vol.Schema:
    outside_key = vol.Required(CONF_OUTSIDE, default=outside) if outside else vol.Required(CONF_OUTSIDE)
    return vol.Schema(
        {
            vol.Required(CONF_ROOMS, default=rooms): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            outside_key: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
        }
    )


class WiserPredictiveConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Wiser Predictive", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(discover_rooms(self.hass), None))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PredictiveOptionsFlow()


class PredictiveOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current.get(CONF_ROOMS, []), current.get(CONF_OUTSIDE)),
        )
