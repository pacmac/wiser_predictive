"""Config flow: select the Wiser hub (skipped when there is only one), then the rooms and the outside sensor.
Rooms are discovered from the selected hub. Editable later through the options flow (the hub is fixed)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import hub as hubs
from . import model
from .const import CONF_HUB, CONF_OUTSIDE, CONF_ROOMS, DOMAIN


def _schema(rooms: list[str], outside: str | None, allowed: list[str]) -> vol.Schema:
    outside_key = vol.Required(CONF_OUTSIDE, default=outside) if outside else vol.Required(CONF_OUTSIDE)
    return vol.Schema(
        {
            vol.Required(CONF_ROOMS, default=rooms): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True, include_entities=allowed)
            ),
            outside_key: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
        }
    )


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
            data_schema=_schema(found, None, found),
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
            data_schema=_schema(current.get(CONF_ROOMS, []), current.get(CONF_OUTSIDE), allowed),
            description_placeholders={"hub": hubs.hub_name(self.hass, hub_id) if hub_id else "unknown"},
        )
