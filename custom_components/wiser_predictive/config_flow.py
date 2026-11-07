"""Config flow: pick the rooms and the outside sensor. Editable later through the options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_OUTSIDE, CONF_ROOMS, DEFAULT_OUTSIDE, DEFAULT_ROOMS, DOMAIN


def _schema(rooms: list[str], outside: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ROOMS, default=rooms): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            vol.Required(CONF_OUTSIDE, default=outside): selector.EntitySelector(
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
        return self.async_show_form(step_id="user", data_schema=_schema(DEFAULT_ROOMS, DEFAULT_OUTSIDE))

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
            data_schema=_schema(
                current.get(CONF_ROOMS, DEFAULT_ROOMS), current.get(CONF_OUTSIDE, DEFAULT_OUTSIDE)
            ),
        )
