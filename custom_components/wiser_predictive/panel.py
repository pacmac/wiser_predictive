"""The sidebar panel ("Predictive Heating") and the websocket command that feeds it (docs/SPEC.md, VISUALISATION).

The page itself is frontend/panel.js. It asks `wiser_predictive/chart` for the room's recorded history, the outside
temperature and the forecast, and draws them. Nothing about a house is in here: rooms, the outside sensor and the weather
entity come from the config entry.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import history, series
from .const import CONF_OUTSIDE, CONF_ROOMS, CONF_WEATHER, DOMAIN
from .sensor import room_label

_LOGGER = logging.getLogger(__name__)

STATIC_URL = "/wiser_predictive_static"
PANEL_PATH = "wiser-predictive"
FRONTEND = Path(__file__).parent / "frontend"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def outside_series(states: list, from_attribute: bool) -> list[tuple[float, float]]:
    """[(seconds, degrees C)] from a temperature sensor's states, or from a weather entity's `temperature` attribute."""
    out = []
    for s in states:
        value = _number(s.attributes.get("temperature") if from_attribute else s.state)
        if value is not None:
            out.append((s.last_updated.timestamp(), value))
    return out


def forecast_series(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    out = []
    for row in rows:
        value = _number(row.get("temperature"))
        if value is not None and row.get("datetime"):
            out.append((datetime.datetime.fromisoformat(row["datetime"]).timestamp(), value))
    return out


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wiser_predictive/chart",
        vol.Optional("entry_id"): str,
        vol.Optional("room"): str,
        vol.Optional("days", default=3): vol.All(int, vol.Range(min=1, max=10)),
    }
)
@websocket_api.async_response
async def ws_chart(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_configured", "Wiser Predictive is not set up")
        return
    entry = next((e for e in entries if e.entry_id == msg.get("entry_id")), entries[0])
    cfg = {**entry.data, **entry.options}
    rooms: list[str] = list(cfg.get(CONF_ROOMS, []))
    listing = [
        {"entry_id": e.entry_id, "title": e.title,
         "rooms": [{"entity_id": r, "name": room_label(hass, r)} for r in {**e.data, **e.options}.get(CONF_ROOMS, [])]}
        for e in entries
    ]
    if not rooms:
        connection.send_result(msg["id"], {"entries": listing, "entry_id": entry.entry_id, "room": None, "chart": None})
        return
    # Opens on the active (non-passive) room, the one that calls for heat, else the first. A passive room takes free heat.
    active = next((r for r in rooms if (s := hass.states.get(r)) is not None and s.attributes.get("is_passive") is False), rooms[0])
    room = msg.get("room") if msg.get("room") in rooms else active
    outside_entity, weather = cfg.get(CONF_OUTSIDE) or None, cfg.get(CONF_WEATHER) or None
    now = dt_util.utcnow()
    start = now - datetime.timedelta(days=msg["days"])
    wanted = [room] + ([outside_entity] if outside_entity else [weather] if weather else [])
    notes: list[str] = []
    try:
        states = await history.fetch(hass, wanted, start, now)
    except Exception as err:  # the recorder may be off or busy: say so on the panel, do not draw a made-up line
        _LOGGER.warning("history unavailable: %s", err)
        states, notes = {}, [f"History could not be read: {err}"]
    climate = [(s.last_updated.timestamp(), dict(s.attributes)) for s in states.get(room, [])]
    outside = outside_series(states.get(outside_entity or weather, []), from_attribute=not outside_entity) if wanted[1:] else []
    if not wanted[1:]:
        notes.append("No outside temperature sensor or weather entity is set: choose one in the options.")
    forecast: list[tuple[float, float]] = []
    if weather:
        try:
            forecast = forecast_series(await history.hourly_forecast(hass, weather))
        except Exception as err:
            _LOGGER.warning("forecast unavailable: %s", err)
            notes.append(f"No forecast: {err}")
    else:
        notes.append("No weather entity is set, so there is no forecast: choose one in the options.")
    chart = series.build(room_label(hass, room), climate, outside, forecast, now.timestamp(), notes)
    connection.send_result(msg["id"], {"entries": listing, "entry_id": entry.entry_id, "room": room, "chart": chart})


async def async_register(hass: HomeAssistant) -> None:
    """Once per Home Assistant, however many entries: the websocket command, the static files and the sidebar entry."""
    state = hass.data.setdefault(DOMAIN, {})
    if state.get("panel_registered"):
        return
    state["panel_registered"] = True
    websocket_api.async_register_command(hass, ws_chart)
    await register_panel(hass)


async def register_panel(hass: HomeAssistant) -> None:
    http = getattr(hass, "http", None)
    if http is None:  # no web server (tests)
        return
    from homeassistant.components import panel_custom
    from homeassistant.components.http import StaticPathConfig

    await http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(FRONTEND), False)])
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="wiser-predictive-panel",
        frontend_url_path=PANEL_PATH,
        module_url=f"{STATIC_URL}/panel.js",
        sidebar_title="Predictive Heating",
        sidebar_icon="mdi:chart-line",
        require_admin=False,
        config={},
    )
