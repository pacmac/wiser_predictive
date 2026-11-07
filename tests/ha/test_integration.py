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
