"""Constants for Wiser Predictive."""

DOMAIN = "wiser_predictive"

CONF_ROOMS = "rooms"
CONF_OUTSIDE = "outside_sensor"

# Rooms read from the box 2026-11-07. climate.wiser_hot_water is a hot water channel, not a room.
DEFAULT_ROOMS = [
    "climate.wiser_lounge",
    "climate.wiser_kitchen",
    "climate.wiser_bed_1",
    "climate.wiser_bed_2",
    "climate.wiser_bed_3",
    "climate.wiser_bath",
    "climate.wiser_toilet",
]
# Garage roofspace: r 0.88 with the forecast over 9 days (named "Plant Dryer"; it dries nothing).
DEFAULT_OUTSIDE = "sensor.ewelink_th01_temperature"
