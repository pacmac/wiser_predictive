"""Home Assistant side: read the recorder's history and the weather forecast for the panel."""
from __future__ import annotations

import datetime
from typing import Any

from homeassistant.core import HomeAssistant, State


async def fetch(hass: HomeAssistant, entity_ids: list[str], start: datetime.datetime, end: datetime.datetime) -> dict[str, list[State]]:
    """Every state (attribute changes included) of the entities between start and end, from the recorder."""
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import get_significant_states

    return await get_instance(hass).async_add_executor_job(
        lambda: get_significant_states(
            hass, start, end, entity_ids,
            include_start_time_state=True, significant_changes_only=False, minimal_response=False, no_attributes=False,
        )
    )


async def hourly_forecast(hass: HomeAssistant, weather_entity: str) -> list[dict[str, Any]]:
    """The weather entity's hourly forecast: [{'datetime': iso string, 'temperature': degrees C, ...}]."""
    response = await hass.services.async_call(
        "weather", "get_forecasts", {"entity_id": weather_entity, "type": "hourly"}, blocking=True, return_response=True
    )
    return list((response or {}).get(weather_entity, {}).get("forecast", []))
