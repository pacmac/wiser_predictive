"""Wiser Predictive: keeps every Wiser room above its minimum by acting before the minimum is reached."""
from __future__ import annotations

import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

PLATFORMS = ["sensor", "binary_sensor"]
LEARN_EVERY = datetime.timedelta(hours=6)  # the recorder keeps 10 days; a day is kept within 6 hours of ending, with a margin of weeks


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from . import learner, panel

    await panel.async_register(hass)
    entry.async_on_unload(entry.add_update_listener(_reload))

    async def learn_now(_now=None) -> None:
        await learner.update_all(hass, entry)

    # Remember each completed day: now, and every LEARN_EVERY. The recorder keeps 10 days, so a 6-hour interval keeps every day
    # long before it is purged, with or without anyone opening the panel.
    if "recorder" in hass.config.components:
        entry.async_on_unload(async_track_time_interval(hass, learn_now, LEARN_EVERY))
        hass.async_create_background_task(learn_now(), f"{DOMAIN} learn")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
