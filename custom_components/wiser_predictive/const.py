"""Constants for Wiser Predictive. Nothing here may name an entity, room, hub or site (docs/SPEC.md)."""

DOMAIN = "wiser_predictive"
WISER = "wiser"  # the integration this one reads; each Wiser hub is one config entry of it

CONF_HUB = "hub"  # config entry id of the selected Wiser hub
CONF_ROOMS = "rooms"
CONF_OUTSIDE = "outside_sensor"
CONF_WEATHER = "weather_entity"  # the weather entity whose hourly forecast the panel draws (and outside, if no sensor is chosen)
CONF_WALL_FACTOR = "wall_factor"  # humidity.py: how warm the inside of an external wall is, 0 (as cold as outside) to 1 (as warm as the room)
CONF_INDOOR_DAMP = "indoor_damp"  # humidity.py: the room's water vapour as a multiple of the outdoor air's
CONF_GAS_KWH_H = "gas_kwh_per_hour"  # kWh of gas the boiler burns in an hour at full demand, from the house's own meter (0 = not set)
CONF_GAS_PRICE = "gas_price"  # currency units per kWh of gas (0 = not set)
CONF_TRIGGER = "trigger_margin"
CONF_ANNOUNCE_SCRIPT = "announce_script"
CONF_ANNOUNCE_DATA = "announce_data"

# Degrees C above a room's minimum at which heat is needed. One step of the 0.1 C room sensor: in the 8-day replay it was the
# only offset of 0.1-0.4 that caught all 9 touches of the lounge minimum (docs/SPEC.md, MODEL).
DEFAULT_TRIGGER = 0.1

from .humidity import DEFAULT_INDOOR_DAMP, DEFAULT_WALL_FACTOR  # noqa: E402,F401  (derived beside the values, in humidity.py)
