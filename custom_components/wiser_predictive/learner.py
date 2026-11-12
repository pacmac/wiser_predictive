"""Home Assistant side of continuous learning: keeps each room's per-day sums (learning.py) in Home Assistant's storage, so what a room
has been like outlives the recorder's 10 days, and works out the room's character and model from every day kept."""
from __future__ import annotations

import datetime
import logging
from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import history, humidity, learning, thermal
from .const import CONF_OUTSIDE, CONF_ROOMS, CONF_WEATHER, DOMAIN

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
LEARN_DAYS = 10  # days read from the recorder each time (its default keeps 10); the sums of every completed day are kept after that


class Learned:
    """{room entity id: {day number: sums}} on disk, loaded once."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.learned")
        self._rooms: dict[str, dict[int, list[float]]] | None = None
        self._weather: dict[int, list[float]] = {}  # {hour start (seconds): [outside temperature, outside humidity]}, what the weather entity said

    async def _load(self) -> dict[str, dict[int, list[float]]]:
        if self._rooms is None:
            raw = await self._store.async_load() or {}
            self._rooms = {room: {int(d): list(s) for d, s in days.items()} for room, days in raw.get("rooms", {}).items()}
            self._weather = {int(h): list(v) for h, v in raw.get("weather", {}).items()}
        return self._rooms

    def _save(self) -> None:
        rooms = self._rooms or {}
        self._store.async_delay_save(
            lambda: {"rooms": {r: {str(d): s for d, s in days.items()} for r, days in rooms.items()},
                     "weather": {str(h): v for h, v in self._weather.items()}}, 5)

    async def weather(self) -> dict[int, list[float]]:
        await self._load()
        return dict(self._weather)

    async def remember_weather(self, hours: list[tuple[float, float, float]]) -> None:
        """Keep each completed hour's outside temperature and humidity. The recorder keeps the weather entity's states for 10 days
        and the forecast is not kept at all, so a month of humidity (the monthly limit) exists only if it is kept here. About 8,760
        hours a year at about 28 bytes each is 245 kB a year."""
        await self._load()
        changed = False
        for h, temp, rh in hours:
            row = [round(temp, 2), round(rh, 1)]
            if self._weather.get(int(h)) != row:
                self._weather[int(h)] = row
                changed = True
        if changed:
            self._save()

    async def days(self, room: str) -> dict[int, list[float]]:
        return dict((await self._load()).get(room, {}))

    async def remember(self, room: str, complete: dict[int, list[float]]) -> None:
        rooms = await self._load()
        merged = learning.merge(rooms.get(room, {}), complete)
        if merged != rooms.get(room):
            rooms[room] = merged
            self._save()


async def learned(hass: HomeAssistant) -> Learned:
    state = hass.data.setdefault(DOMAIN, {})
    if "learned" not in state:
        state["learned"] = Learned(hass)
    return state["learned"]


async def learn(hass: HomeAssistant, room: str, climate, outside, now: float) -> dict[str, Any] | None:
    """Remember the room's completed days, then fit from every day kept. Returns {character, params, info} or None when there is too
    little free cooling to learn from. `climate` and `outside` are what the recorder holds (the last LEARN_DAYS)."""
    prepared = thermal.prepare(climate, outside)
    if prepared is None:
        return None
    grid, temps, heating, outs = prepared
    fresh = learning.day_stats(grid, thermal.cooling_windows(temps, heating, outs))
    today = int(now // learning.DAY_S)
    store = await learned(hass)
    await store.remember(room, {d: s for d, s in fresh.items() if d < today})  # a day is kept only once it is over
    stats = learning.merge(await store.days(room), fresh)  # today's partial day counts for the answer, not for the memory
    found = learning.summarise(stats, today)
    if found is None:
        return None
    return {"character": asdict(found["character"]), "params": found["params"], "info": found["info"]}


async def update_all(hass: HomeAssistant, entry) -> None:
    """Read the recorder and remember every chosen room's completed days. Run at start-up and every few hours, so a day is kept
    well inside the recorder's retention even if nobody opens the panel."""
    cfg = {**entry.data, **entry.options}
    rooms: list[str] = list(cfg.get(CONF_ROOMS, []))
    outside_entity, weather = cfg.get(CONF_OUTSIDE) or None, cfg.get(CONF_WEATHER) or None
    source = outside_entity or weather
    if not rooms or not source:
        return
    from .panel import outside_series  # the same reading of the outside sensor as the panel uses

    now = dt_util.utcnow()
    wanted = rooms + [source] + ([weather] if weather and weather != source else [])
    try:
        states = await history.fetch(hass, wanted, now - datetime.timedelta(days=LEARN_DAYS), now)
    except Exception as err:  # the recorder may not be ready yet; the next run tries again
        _LOGGER.debug("learning skipped, history unavailable: %s", err)
        return
    if weather:  # keep the weather's humidity too, once each hour is over (see Learned.remember_weather)
        hours = humidity.hourly_from_states([(s.last_updated.timestamp(), dict(s.attributes)) for s in states.get(weather, [])])
        await (await learned(hass)).remember_weather([w for w in hours if w[0] + humidity.HOUR <= now.timestamp()])
    outside = outside_series(states.get(source, []), from_attribute=not outside_entity)
    for room in rooms:
        climate = [(s.last_updated.timestamp(), dict(s.attributes)) for s in states.get(room, [])]
        await learn(hass, room, climate, outside, now.timestamp())
