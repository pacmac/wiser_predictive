"""The HA-side code under a real Home Assistant (pytest-homeassistant-custom-component).

Run in a venv that has it:  <venv>/bin/python -m pytest tests/ha -q
Without it the whole file is skipped, so the plain `pytest tests` run still works.

The world is built the way the real Wiser integration lays it out: one config entry per hub, a hub device, room devices
connected via the hub, room climate entities carrying is_passive, and a hot water climate entity that does not.
"""
import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers import device_registry as dr, entity_registry as er  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service  # noqa: E402

pytestmark = pytest.mark.asyncio

DOMAIN = "wiser_predictive"
OUTSIDE = "sensor.some_outside_thermometer"
LOUNGE = {"name": "Lounge", "current_temperature": 12.6, "temperature": 12.5, "is_passive": False,
          "is_boosted": False, "is_override": False, "is_heating": False}
BED = {"name": "Bed 3", "current_temperature": 12.8, "target_temp_low": 12.0, "target_temp_high": 21.0,
       "is_passive": True, "is_boosted": False, "is_override": False, "is_heating": False}
TOILET = {"name": "Toilet", "current_temperature": None, "target_temp_low": 12.0, "target_temp_high": 21.0,
          "is_passive": True, "is_boosted": False, "is_override": False, "is_heating": False}
HOT_WATER = {"name": "Hot Water", "current_temperature": None, "target_temp_low": 45.0, "target_temp_high": 55.0,
             "is_boosted": False, "is_override": False}


@pytest.fixture(autouse=True)
def _custom(enable_custom_integrations):
    yield


def add_hub(hass, hub_id, hub_name, climates):
    """climates: {entity_id: attributes}. Returns the hub's config entry."""
    entry = MockConfigEntry(domain="wiser", entry_id=hub_id, title=hub_name)
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    hub = devices.async_get_or_create(config_entry_id=hub_id, identifiers={("wiser", f"hub-{hub_id}")}, name=hub_name)
    for entity_id, attrs in climates.items():
        object_id = entity_id.split(".", 1)[1]
        dev = devices.async_get_or_create(
            config_entry_id=hub_id, identifiers={("wiser", object_id)}, name=attrs["name"], via_device=("wiser", f"hub-{hub_id}")
        )
        er.async_get(hass).async_get_or_create(
            "climate", "wiser", object_id, config_entry=entry, device_id=dev.id, suggested_object_id=object_id
        )
        hass.states.async_set(entity_id, "heat", attrs)
    return entry, hub


async def start_flow(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


ROOMS_STEP = {"outside_sensor": OUTSIDE, "trigger_margin": 0.1}


async def test_no_wiser_aborts(hass):
    result = await start_flow(hass)
    assert result["type"] == FlowResultType.ABORT and result["reason"] == "no_wiser"


async def test_one_hub_skips_the_hub_step_and_offers_its_rooms_but_not_hot_water(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE, "climate.bed_3": BED, "climate.hot_water": HOT_WATER})
    result = await start_flow(hass)
    assert result["type"] == FlowResultType.FORM and result["step_id"] == "rooms"
    default_rooms = next(k.default() for k in result["data_schema"].schema if k == "rooms")
    assert sorted(default_rooms) == ["climate.bed_3", "climate.lounge"]
    done = await hass.config_entries.flow.async_configure(result["flow_id"], {"rooms": default_rooms, **ROOMS_STEP})
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert done["title"] == "Wiser Predictive (Wiser HeatHub (AAA))"
    assert done["data"]["hub"] == "hub-a" and done["data"]["trigger_margin"] == 0.1


async def test_two_hubs_ask_which_and_a_hub_without_rooms_is_refused(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    add_hub(hass, "hub-b", "Wiser HeatHub (BBB)", {"climate.hot_water": HOT_WATER})
    result = await start_flow(hass)
    assert result["step_id"] == "user"
    refused = await hass.config_entries.flow.async_configure(result["flow_id"], {"hub": "hub-b"})
    assert refused["step_id"] == "rooms" and refused["errors"] == {"base": "no_rooms"}
    again = await start_flow(hass)
    ok = await hass.config_entries.flow.async_configure(again["flow_id"], {"hub": "hub-a"})
    assert ok["step_id"] == "rooms" and not ok.get("errors")


async def test_the_outside_sensor_is_optional_because_the_margin_rule_does_not_use_it(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    result = await start_flow(hass)
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rooms": ["climate.lounge"], "trigger_margin": 0.1}
    )
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert "outside_sensor" not in done["data"]
    await hass.async_block_till_done()  # creating the entry also sets it up
    assert hass.states.get("sensor.wiser_predictive_lounge_margin").state == "0.1"


async def test_a_hub_already_set_up_is_not_offered_twice(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    first = await start_flow(hass)
    await hass.config_entries.flow.async_configure(first["flow_id"], {"rooms": ["climate.lounge"], **ROOMS_STEP})
    second = await start_flow(hass)
    assert second["type"] == FlowResultType.ABORT and second["reason"] == "already_configured"


async def setup_entry(hass, rooms, **extra):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="hub-a", title="Wiser Predictive (Wiser HeatHub (AAA))",
        data={"hub": "hub-a", "rooms": rooms, "outside_sensor": OUTSIDE, "trigger_margin": 0.1, **extra},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_show_real_margins_the_hub_and_unknown_placeholders(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE, "climate.bed_3": BED, "climate.toilet": TOILET})
    await setup_entry(hass, ["climate.lounge", "climate.bed_3", "climate.toilet"])
    assert hass.states.get("sensor.wiser_predictive_lounge_margin").state == "0.1"
    assert hass.states.get("sensor.wiser_predictive_bed_3_margin").state == "0.8"
    assert hass.states.get("sensor.wiser_predictive_toilet_margin").state == "unavailable"  # no reading from that thermostat
    assert hass.states.get("sensor.wiser_predictive_bed_3_time_to_minimum") is None  # the placeholder is gone
    low = hass.states.get("sensor.wiser_predictive_lowest_margin")
    assert low.state == "0.1" and low.attributes["room"] == "Lounge" and low.attributes["rooms_without_a_reading"] == ["Toilet"]
    assert hass.states.get("sensor.wiser_predictive_trigger_margin").state == "0.1"
    assert hass.states.get("sensor.wiser_predictive_hub").state == "Wiser HeatHub (AAA)"
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, next(iter(hass.config_entries.async_entries(DOMAIN))).entry_id)})
    hub = dr.async_get(hass).async_get_device(identifiers={("wiser", "hub-hub-a")})
    assert device.via_device_id == hub.id


async def test_heat_needed_follows_the_margin_rule_and_announces_once_per_episode(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE, "climate.bed_3": BED, "climate.toilet": TOILET})
    calls = async_mock_service(hass, "script", "turn_on")
    await setup_entry(
        hass, ["climate.lounge", "climate.bed_3", "climate.toilet"],
        announce_script="script.speak", announce_data={"target": "both", "chime": True},
    )
    heat = "binary_sensor.wiser_predictive_heat_needed"
    # start-up: lounge margin 0.1 is already on, and nothing is announced
    assert hass.states.get(heat).state == "on" and calls == []

    def lounge(temp, **flags):
        hass.states.async_set("climate.lounge", "heat", {**LOUNGE, "current_temperature": temp, **flags})

    lounge(12.9)  # margin 0.4 >= 0.1 + 0.2: episode over
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "off"
    lounge(12.6)  # margin 0.1: on again, a room known off turned on -> announce
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "on"
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "script.speak"
    assert calls[0].data["variables"] == {"target": "both", "chime": True, "message": "Lounge is 0.1 degrees above its minimum"}
    lounge(12.7)  # margin 0.2: between the thresholds, keeps its state, no new announcement
    lounge(12.6)
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "on" and len(calls) == 1
    lounge(12.4, is_heating=True)  # the boiler is calling: episode over
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "off"
    assert hass.states.get(heat).attributes["rooms_on"] == []


async def test_a_boost_raises_the_target_but_margins_stay_against_the_real_minimum(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    await setup_entry(hass, ["climate.lounge"])
    margin = "sensor.wiser_predictive_lounge_margin"
    assert hass.states.get(margin).state == "0.1"
    hass.states.async_set("climate.lounge", "auto", {**LOUNGE, "current_temperature": 17.6, "temperature": 20.5,
                                                    "is_boosted": True, "is_override": True, "is_heating": True})
    await hass.async_block_till_done()
    boosted = hass.states.get(margin)
    assert boosted.state == "5.1" and boosted.attributes["minimum"] == 12.5 and boosted.attributes["minimum_held_during_boost"]
    assert hass.states.get("sensor.wiser_predictive_lowest_margin").state == "5.1"
    assert hass.states.get("binary_sensor.wiser_predictive_heat_needed").state == "off"
    hass.states.async_set("climate.lounge", "auto", {**LOUNGE, "current_temperature": 17.0})
    await hass.async_block_till_done()
    assert hass.states.get(margin).state == "4.5" and not hass.states.get(margin).attributes["minimum_held_during_boost"]


async def test_the_schedule_raising_the_target_is_not_announced_as_a_cooling_room(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    calls = async_mock_service(hass, "script", "turn_on")
    await setup_entry(hass, ["climate.lounge"], announce_script="script.speak")
    heat = "binary_sensor.wiser_predictive_heat_needed"

    def lounge(temp, target):
        hass.states.async_set("climate.lounge", "auto", {**LOUNGE, "current_temperature": temp, "temperature": target})

    lounge(13.5, 12.5)  # off: margin 1.0
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "off"
    lounge(13.5, 19.0)  # the schedule steps the target up: margin -5.5, but the room did not cool
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "off" and calls == []
    lounge(19.2, 19.0)  # climbing, margin 0.2: still quiet
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "off"
    lounge(19.3, 19.0)  # margin 0.3: armed again
    await hass.async_block_till_done()
    lounge(19.1, 19.0)  # now it really is cooling toward the minimum
    await hass.async_block_till_done()
    assert hass.states.get(heat).state == "on" and len(calls) == 1


async def test_started_in_the_middle_of_a_boost_the_margin_is_unavailable_not_nonsense(hass):
    boosted = {**LOUNGE, "current_temperature": 17.6, "temperature": 20.5, "is_boosted": True, "is_override": True}
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": boosted})
    await setup_entry(hass, ["climate.lounge"])
    assert hass.states.get("sensor.wiser_predictive_lounge_margin").state == "unavailable"
    assert hass.states.get("sensor.wiser_predictive_lowest_margin").state == "unknown"


async def test_the_old_time_to_minimum_entities_are_removed_on_setup(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    entry = MockConfigEntry(domain=DOMAIN, unique_id="hub-a", data={"hub": "hub-a", "rooms": ["climate.lounge"], "trigger_margin": 0.1})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_climate.lounge_time_to_minimum", config_entry=entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None


async def test_a_flat_battery_room_does_not_hold_heat_needed_unknown(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.bed_3": BED, "climate.toilet": TOILET})
    await setup_entry(hass, ["climate.bed_3", "climate.toilet"])
    assert hass.states.get("binary_sensor.wiser_predictive_heat_needed").state == "off"


async def test_with_no_announce_script_nothing_is_called(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    calls = async_mock_service(hass, "script", "turn_on")
    await setup_entry(hass, ["climate.lounge"])
    hass.states.async_set("climate.lounge", "heat", {**LOUNGE, "current_temperature": 12.9})
    await hass.async_block_till_done()
    hass.states.async_set("climate.lounge", "heat", {**LOUNGE, "current_temperature": 12.6})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.wiser_predictive_heat_needed").state == "on" and calls == []


async def test_options_change_the_trigger_and_keep_the_hub(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    entry = await setup_entry(hass, ["climate.lounge"])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == FlowResultType.FORM and flow["description_placeholders"] == {"hub": "Wiser HeatHub (AAA)"}
    done = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"rooms": ["climate.lounge"], "outside_sensor": OUTSIDE, "trigger_margin": 0.3}
    )
    assert done["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["trigger_margin"] == 0.3 and entry.data["hub"] == "hub-a"


# --- the panel: websocket command, registration, the weather suggestion ------------------------------------------------

import datetime  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from homeassistant.core import State  # noqa: E402

from custom_components.wiser_predictive import history as history_mod, panel as panel_mod  # noqa: E402

NOW = datetime.datetime(2026, 11, 7, 10, 0, tzinfo=datetime.timezone.utc)


def _state(entity_id, state, attrs, minutes_ago):
    t = NOW - datetime.timedelta(minutes=minutes_ago)
    return State(entity_id, state, attrs, last_changed=t, last_updated=t)


async def _chart(hass, hass_ws_client, states, forecast=None, **msg):
    client = await hass_ws_client(hass)
    with patch.object(history_mod, "fetch", AsyncMock(return_value=states) if not isinstance(states, Exception) else AsyncMock(side_effect=states)), \
            patch.object(history_mod, "hourly_forecast", AsyncMock(return_value=forecast or [])), \
            patch("homeassistant.util.dt.utcnow", return_value=NOW):
        await client.send_json({"id": 1, "type": "wiser_predictive/chart", **msg})
        return await client.receive_json()


async def test_the_panel_command_returns_the_room_outside_forecast_and_heating(hass, hass_ws_client):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE, "climate.bed_3": BED})
    await setup_entry(hass, ["climate.lounge", "climate.bed_3"], weather_entity="weather.home", outside_sensor=OUTSIDE)
    states = {
        "climate.lounge": [_state("climate.lounge", "heat", {**LOUNGE, "current_temperature": 12.5}, 120),
                           _state("climate.lounge", "heat", {**LOUNGE, "current_temperature": 13.0, "is_heating": True}, 60),
                           _state("climate.lounge", "heat", {**LOUNGE, "current_temperature": 13.4}, 30)],
        OUTSIDE: [_state(OUTSIDE, "7.5", {}, 100), _state(OUTSIDE, "unavailable", {}, 50), _state(OUTSIDE, "6.9", {}, 10)],
    }
    forecast = [{"datetime": "2026-11-07T11:00:00+00:00", "temperature": 6.0}, {"datetime": "2026-11-07T12:00:00+00:00", "temperature": 5.5}]
    reply = await _chart(hass, hass_ws_client, states, forecast)
    assert reply["success"], reply
    result, chart = reply["result"], reply["result"]["chart"]
    assert result["room"] == "climate.lounge"
    assert [r["name"] for r in result["entries"][0]["rooms"]] == ["Lounge", "Bed 3"]
    assert [v for _, v in chart["reading"]] == [12.5, 13.0, 13.4]
    assert [v for _, v in chart["outside"]] == [7.5, 6.9]  # 'unavailable' is skipped, not drawn as a value
    assert [v for _, v in chart["forecast"]] == [6.0, 5.5]
    start, end = chart["heating"][0]
    assert end - start == 30 * 60  # heating from the 60-minutes-ago row to the next row
    assert chart["prediction"] is None and "Not enough free-cooling history" in " ".join(chart["notes"])  # 2 hours of history is not enough to learn


async def test_the_panel_opens_on_the_active_room_not_the_first_in_the_list(hass, hass_ws_client):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE, "climate.bed_3": BED})
    await setup_entry(hass, ["climate.bed_3", "climate.lounge"])  # the passive room is listed first
    reply = await _chart(hass, hass_ws_client, {})
    assert reply["result"]["room"] == "climate.lounge"
    other = await _chart(hass, hass_ws_client, {}, room="climate.bed_3")
    assert other["result"]["room"] == "climate.bed_3"  # an explicit choice is kept


async def test_the_panel_command_uses_the_weather_entitys_temperature_when_there_is_no_sensor(hass, hass_ws_client):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    await setup_entry(hass, ["climate.lounge"], weather_entity="weather.home", outside_sensor=None)
    states = {"climate.lounge": [_state("climate.lounge", "heat", LOUNGE, 5)],
              "weather.home": [_state("weather.home", "cloudy", {"temperature": 8.2}, 60)]}
    reply = await _chart(hass, hass_ws_client, states, room="climate.lounge", days=10)
    assert [v for _, v in reply["result"]["chart"]["outside"]] == [8.2]


async def test_the_panel_says_what_is_missing_instead_of_drawing_nothing_silently(hass, hass_ws_client):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    await setup_entry(hass, ["climate.lounge"], outside_sensor=None)  # no weather entity, no outside sensor
    reply = await _chart(hass, hass_ws_client, {"climate.lounge": [_state("climate.lounge", "heat", LOUNGE, 5)]})
    notes = " ".join(reply["result"]["chart"]["notes"])
    assert "No outside temperature" in notes and "no forecast" in notes
    broken = await _chart(hass, hass_ws_client, RuntimeError("recorder is off"))
    assert broken["result"]["chart"]["reading"] == [] and "History could not be read" in " ".join(broken["result"]["chart"]["notes"])


async def test_the_command_errors_when_the_integration_has_no_entry(hass, hass_ws_client):
    from custom_components.wiser_predictive import panel
    panel.websocket_api.async_register_command(hass, panel.ws_chart)
    reply = await _chart(hass, hass_ws_client, {})
    assert not reply["success"] and reply["error"]["code"] == "not_configured"


async def test_the_gas_for_a_run_is_shown_only_when_the_options_give_the_boilers_draw_and_the_price():
    def predicted():
        return {"plan": {"runs": [{"minutes": 30}, {"minutes": 60}]}}

    p = predicted()
    panel_mod.with_gas({}, p)  # nothing set: no made-up cost
    assert "kwh" not in p["plan"]["runs"][0]
    p = predicted()
    panel_mod.with_gas({"gas_kwh_per_hour": 9.0}, p)  # draw but no price: kWh only
    assert p["plan"]["runs"][0]["kwh"] == 4.5 and "pence" not in p["plan"]["runs"][0] and p["plan"]["runs"][1]["kwh"] == 9.0
    p = predicted()
    panel_mod.with_gas({"gas_kwh_per_hour": 9.0, "gas_price": 0.1}, p)
    assert p["plan"]["runs"][0]["pence"] == 45.0  # 4.5 kWh at 0.10 a kWh is 0.45, in hundredths
    panel_mod.with_gas({"gas_kwh_per_hour": 9.0}, None)  # no prediction: nothing to do, no error


async def test_the_sidebar_panel_is_registered_once_however_many_entries(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    add_hub(hass, "hub-b", "Wiser HeatHub (BBB)", {"climate.bed_3": BED})
    with patch.object(panel_mod, "register_panel", AsyncMock()) as register:
        await setup_entry(hass, ["climate.lounge"])
        entry = MockConfigEntry(domain=DOMAIN, unique_id="hub-b", data={"hub": "hub-b", "rooms": ["climate.bed_3"], "trigger_margin": 0.1})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    assert register.await_count == 1


async def test_the_only_weather_entity_is_suggested_and_two_are_not(hass):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    hass.states.async_set("weather.home", "cloudy", {})
    result = await start_flow(hass)
    suggested = next(k.description["suggested_value"] for k in result["data_schema"].schema if k == "weather_entity")
    assert suggested == "weather.home"
    hass.config_entries.flow.async_abort(result["flow_id"])  # a second flow for the same hub would be "already in progress"
    hass.states.async_set("weather.other", "sunny", {})
    again = await start_flow(hass)
    assert next(k.description["suggested_value"] for k in again["data_schema"].schema if k == "weather_entity") is None


async def test_the_panel_learns_the_rooms_cooling_and_predicts_the_next_day(hass, hass_ws_client):
    import math

    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    await setup_entry(hass, ["climate.lounge"], weather_entity="weather.home", outside_sensor=OUTSIDE)
    steps, t = 5 * 144, 19.0  # 5 days of 10-minute states of a room that cools with tau 20 h toward 0.25/h gains and the outside
    lounge_states, outside_states = [], []
    for k in range(steps):
        h = k / 6.0
        out = 8.0 + 3.0 * math.sin(2 * math.pi * h / 24)
        ago = (steps - k) * 10
        lounge_states.append(_state("climate.lounge", "heat", {**LOUNGE, "current_temperature": round(t, 2), "temperature": 12.5}, ago))
        outside_states.append(_state(OUTSIDE, f"{out:.2f}", {}, ago))
        t += (1 / 6) * (0.25 - t / 20.0 + 0.03 * out)
    forecast = [{"datetime": (NOW + datetime.timedelta(hours=k)).isoformat(), "temperature": 8.0, "humidity": 88.0} for k in range(1, 30)]
    weather_states = [_state("weather.home", "cloudy", {"temperature": 8.0, "humidity": 88.0}, 60 * m) for m in range(5 * 24, 0, -1)]  # hourly, 5 days
    reply = await _chart(hass, hass_ws_client, {"climate.lounge": lounge_states, OUTSIDE: outside_states, "weather.home": weather_states}, forecast)
    chart = reply["result"]["chart"]
    p = chart["prediction"]
    assert p is not None, chart["notes"]
    damp = chart["humidity"]  # estimated wall dampness: 8 C at 88% outside, the room's own reading, defaults k 1.14 and f 0.73
    assert damp is not None and damp["k"] == 1.14 and damp["f"] == 0.73
    from custom_components.wiser_predictive import humidity as hum
    e_out = hum.vapour_pressure(8.0, 88.0)
    t_now = chart["reading"][-1][1]
    assert abs(damp["now"]["activity"] - hum.activity(t_now, 8.0, e_out, 1.14, 0.73)) < 0.002 and abs(damp["now"]["dew"] - hum.dew_point(8.0, 88.0)) < 0.01
    assert damp["activity"][-1][0] > chart["now"] and damp["floor"]["day"]["temp"] < damp["floor"]["month"]["temp"]  # the forecast hours are drawn too
    assert damp["means"]["day"]["hours"] == 24 and damp["means"]["month"]["of"] == 720
    assert abs(p["tau_h"] - 20.0) < 1.5
    assert p["minimum"] == 12.5 and "an hour or more" in p["minimum_source"]  # the lounge has no LOW setting: its floor is the target it held
    assert abs(p["horizon_h"] - 29.0) < 0.1 and chart["end"] == int(NOW.timestamp()) + 29 * 3600  # as far as the forecast goes (29 hourly points)
    assert len(p["curve"]) == 59 and p["curve"][0][0] == int(NOW.timestamp())  # a point every 30 minutes, 29 h
    assert abs(p["curve"][-1][1] - 9.8) < 0.5  # the room's equilibrium at a steady 8 C outside: (0.25 + 0.03*8) * 20 = 9.8
    ch = chart["character"]  # the same figures as the header card: time constant, coupling, daily-swing delay, uncertainty
    assert ch is not None and abs(ch["tau_h"] - 20.0) < 1.5 and abs(ch["coupling"] - 0.6) < 0.1 and ch["tau_se_h"] is not None
    assert p["heating_now"] is False
    assert chart["notes"] == ["Not enough heat runs in the history yet to learn how the room heats up, so no heating plan."]  # no boosts in this history


async def test_completed_days_are_kept_so_memory_outlives_the_recorder(hass, hass_ws_client, hass_storage):
    import math
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    await setup_entry(hass, ["climate.lounge"], outside_sensor=OUTSIDE)
    steps, t = 8 * 144, 19.0
    lounge_states, outside_states = [], []
    for k in range(steps):
        d, h = k // 144, (k % 144) / 6.0
        out = 8.0 + 3.0 * math.sin(2 * math.pi * h / 24) + (d % 3)
        reheat = d > 0 and d % 3 == 0 and 6.0 <= h < 7.0
        if reheat:
            t = 19.0
        ago = (steps - k) * 10
        lounge_states.append(_state("climate.lounge", "heat", {**LOUNGE, "current_temperature": round(t, 1), "is_heating": reheat}, ago))
        outside_states.append(_state(OUTSIDE, f"{out:.2f}", {}, ago))
        t += (1 / 6) * (0.25 - t / 20.0 + 0.03 * out)

    async def ask(lounge, outside):
        reply = await _chart(hass, hass_ws_client, {"climate.lounge": lounge, OUTSIDE: outside})
        return reply["result"]["chart"]

    first = await ask(lounge_states, outside_states)
    assert first["learning"]["days"] >= 7, first["notes"]
    # the recorder now holds only the last two days: everything earlier must still be remembered
    recent = 2 * 144
    second = await ask(lounge_states[-recent:], outside_states[-recent:])
    assert second["learning"]["days"] >= 7 and second["character"] is not None
    # and it is on disk, not just in memory
    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(seconds=30))
    await hass.async_block_till_done()
    saved = hass_storage["wiser_predictive.learned"]["data"]["rooms"]["climate.lounge"]
    assert len(saved) >= 6 and all(len(s) == 11 for s in saved.values())


async def test_the_panel_says_why_there_is_no_dampness_estimate(hass, hass_ws_client):
    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    await setup_entry(hass, ["climate.lounge"], weather_entity="weather.home", outside_sensor=OUTSIDE)
    states = {"climate.lounge": [_state("climate.lounge", "heat", LOUNGE, 5)], OUTSIDE: [_state(OUTSIDE, "7.0", {}, 5)],
              "weather.home": [_state("weather.home", "cloudy", {"temperature": 7.0}, 5)]}  # a weather entity that gives no humidity
    chart = (await _chart(hass, hass_ws_client, states, [{"datetime": "2026-11-07T11:00:00+00:00", "temperature": 6.0}]))["result"]["chart"]
    assert chart["humidity"] is None and any("no dampness estimate" in n for n in chart["notes"])


async def test_the_weather_the_recorder_holds_is_kept_hour_by_hour_for_the_month(hass, hass_storage):
    from homeassistant.util import dt as dt_util
    from custom_components.wiser_predictive import learner
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE})
    entry = await setup_entry(hass, ["climate.lounge"], weather_entity="weather.home", outside_sensor=OUTSIDE)
    hours = 30  # hourly states of the weather entity, the last one 5 minutes ago (so its hour is not over)
    weather_states = [_state("weather.home", "cloudy", {"temperature": 7.0 + m * 0.1, "humidity": 80.0 + m}, 60 * (hours - m) + 5) for m in range(hours)]
    fetched = {"climate.lounge": [], OUTSIDE: [], "weather.home": weather_states}
    with patch.object(history_mod, "fetch", AsyncMock(return_value=fetched)), patch("homeassistant.util.dt.utcnow", return_value=NOW):
        await learner.update_all(hass, entry)
        kept = await (await learner.learned(hass)).weather()
    assert len(kept) >= hours - 2 and all(h % 3600 == 0 for h in kept)  # one row per hour, on the hour
    newest = max(kept)
    assert newest + 3600 <= NOW.timestamp()  # only hours that are over
    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(seconds=30))
    await hass.async_block_till_done()
    assert len(hass_storage["wiser_predictive.learned"]["data"]["weather"]) == len(kept)


async def test_the_rooms_command_describes_each_room_with_its_uncertainty(hass, hass_ws_client):
    import math

    add_hub(hass, "hub-a", "Wiser HeatHub (AAA)", {"climate.lounge": LOUNGE, "climate.bed_3": BED})
    await setup_entry(hass, ["climate.lounge", "climate.bed_3"], outside_sensor=OUTSIDE)
    steps, t = 8 * 144, 19.0
    lounge_states, outside_states = [], []
    for k in range(steps):
        out = 8.0 + 3.0 * math.sin(2 * math.pi * (k / 6.0) / 24)
        ago = (steps - k) * 10
        lounge_states.append(_state("climate.lounge", "heat", {**LOUNGE, "current_temperature": round(t, 2)}, ago))
        outside_states.append(_state(OUTSIDE, f"{out:.2f}", {}, ago))
        t += (1 / 6) * (0.25 - t / 20.0 + 0.03 * out)
    client = await hass_ws_client(hass)
    with patch.object(history_mod, "fetch", AsyncMock(return_value={"climate.lounge": lounge_states, OUTSIDE: outside_states, "climate.bed_3": []})), \
            patch("homeassistant.util.dt.utcnow", return_value=NOW):
        await client.send_json({"id": 1, "type": "wiser_predictive/rooms"})
        reply = await client.receive_json()
    assert reply["success"], reply
    by_name = {r["name"]: r["character"] for r in reply["result"]["rooms"]}
    c = by_name["Lounge"]
    assert abs(c["tau_h"] - 20.0) < 1.5 and c["tau_se_h"] is not None and abs(c["coupling"] - 0.6) < 0.1 and 4.5 < c["delay_h"] < 6
    assert set(c["settles"]) == {"5", "8", "11"}
    assert by_name["Bed 3"] is None  # no history: said so, not invented
