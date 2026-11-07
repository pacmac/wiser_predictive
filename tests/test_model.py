"""model.py: the room minimum and the margin above it. Values are the live ones read from the box 2026-11-07."""
import importlib.util
import pathlib
import sys

_p = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "wiser_predictive" / "model.py"
_s = importlib.util.spec_from_file_location("model", _p)
model = importlib.util.module_from_spec(_s)
sys.modules["model"] = model
_s.loader.exec_module(model)

LOUNGE = {"current_temperature": 12.6, "temperature": 12.5, "is_passive": False}
BED_3 = {"current_temperature": 12.8, "target_temp_low": 12.0, "target_temp_high": 21.0, "is_passive": True}
TOILET = {"current_temperature": None, "target_temp_low": 12.0, "target_temp_high": 21.0, "is_passive": True}


def test_passive_room_minimum_is_the_low_value():
    assert model.minimum_of(BED_3) == 12.0


def test_lounge_minimum_is_its_single_target():
    assert model.minimum_of(LOUNGE) == 12.5


def test_margin_is_reading_minus_minimum():
    assert model.margin(LOUNGE) == 0.1
    assert model.margin(BED_3) == 0.8


def test_margin_below_minimum_is_negative():
    assert model.margin({"current_temperature": 12.3, "temperature": 12.5}) == -0.2


def test_no_reading_gives_no_margin():
    assert model.margin(TOILET) is None


def test_no_minimum_gives_no_margin():
    assert model.margin({"current_temperature": 13.0}) is None


def test_heat_needed_comes_on_at_the_trigger_margin_and_below():
    assert model.heat_needed(0.1, was_on=False, trigger=0.1) is True
    assert model.heat_needed(0.0, was_on=False, trigger=0.1) is True
    assert model.heat_needed(-0.3, was_on=False, trigger=0.1) is True


def test_heat_needed_is_off_well_above_the_trigger():
    assert model.heat_needed(0.5, was_on=True, trigger=0.1) is False  # trigger + 0.2 or more: episode over


def test_heat_needed_holds_its_state_in_between_so_a_one_step_flicker_does_not_flap_it():
    assert model.heat_needed(0.2, was_on=True, trigger=0.1) is True
    assert model.heat_needed(0.2, was_on=False, trigger=0.1) is False


def test_heat_needed_is_unknown_without_a_margin():
    assert model.heat_needed(None, was_on=True, trigger=0.1) is None


def test_room_decision_applies_the_margin_rule_to_a_rooms_attributes():
    assert model.room_decision(LOUNGE, was_on=False, trigger=0.1) is True  # margin 0.1
    assert model.room_decision(BED_3, was_on=False, trigger=0.1) is False  # margin 0.8


def test_room_decision_is_unknown_without_a_reading():
    assert model.room_decision(TOILET, was_on=False, trigger=0.1) is None


def test_a_room_being_heated_boosted_or_overridden_is_off_even_below_its_minimum():
    low = {"current_temperature": 12.3, "temperature": 12.5, "is_passive": False}
    assert model.room_decision(low, was_on=True, trigger=0.1) is True
    for flag in ("is_heating", "is_boosted", "is_override"):
        assert model.room_decision({**low, flag: True}, was_on=True, trigger=0.1) is False, flag


def test_announcement_says_where_the_room_is_relative_to_its_minimum():
    assert model.announcement("Lounge", 0.1) == "Lounge is 0.1 degrees above its minimum"
    assert model.announcement("Lounge", 0.0) == "Lounge is at its minimum"
    assert model.announcement("Lounge", -0.2) == "Lounge is 0.2 degrees below its minimum"


def test_house_state_is_on_if_any_room_is_on_off_if_one_is_known_unknown_only_if_none_is():
    assert model.any_room_on([True, False, None]) is True
    assert model.any_room_on([False, None]) is False  # a flat-battery room must not hold it unknown
    assert model.any_room_on([None, None]) is None
    assert model.any_room_on([]) is None


def test_hub_link_uses_the_device_id_where_home_assistant_accepts_it_else_the_identifier():
    # newer HA takes via_device_id (the old via_device is deprecated and goes in 2027.8); older HA only knows via_device
    assert model.hub_link("dev-123", {("wiser", "hub-1")}, accepts_id=True) == {"via_device_id": "dev-123"}
    assert model.hub_link("dev-123", {("wiser", "hub-1")}, accepts_id=False) == {"via_device": ("wiser", "hub-1")}


def test_no_hub_device_means_no_link():
    assert model.hub_link(None, set(), accepts_id=True) == {}
    assert model.hub_link(None, set(), accepts_id=False) == {}


HOT_WATER = {"current_temperature": None, "target_temp_low": 45.0, "target_temp_high": 55.0, "friendly_name": "Wiser Hot Water"}


def test_wiser_rooms_are_recognised_by_is_passive():
    assert model.is_room(LOUNGE)
    assert model.is_room(BED_3)
    assert model.is_room(TOILET)


def test_hot_water_channel_is_not_a_room():
    assert not model.is_room(HOT_WATER)


HUB_A, HUB_B = "hub-a", "hub-b"
CANDIDATES = [
    ("climate.wiser_lounge", HUB_A, LOUNGE),
    ("climate.wiser_bed_3", HUB_A, BED_3),
    ("climate.wiser_toilet", HUB_A, TOILET),
    ("climate.wiser_hot_water", HUB_A, HOT_WATER),
    ("climate.other_room", HUB_B, BED_3),
]


def test_rooms_of_a_hub_are_that_hubs_rooms_only_and_exclude_hot_water():
    assert model.rooms_of_hub(CANDIDATES, HUB_A) == ["climate.wiser_bed_3", "climate.wiser_lounge", "climate.wiser_toilet"]
    assert model.rooms_of_hub(CANDIDATES, HUB_B) == ["climate.other_room"]


def test_a_hub_with_no_rooms_gives_an_empty_list():
    assert model.rooms_of_hub(CANDIDATES, "hub-c") == []
    assert model.rooms_of_hub([("climate.wiser_hot_water", HUB_B, HOT_WATER)], HUB_B) == []


def test_exactly_one_hub_is_selected_automatically():
    assert model.single_hub([HUB_A]) == HUB_A


def test_none_or_several_hubs_need_the_user():
    assert model.single_hub([]) is None
    assert model.single_hub([HUB_A, HUB_B]) is None


def test_room_name_prefers_name_then_friendly_name_then_entity_id():
    assert model.room_name("climate.wiser_bed_3", {"name": "Bed 3", "friendly_name": "Wiser Bed 3 Heating"}) == "Bed 3"
    assert model.room_name("climate.x", {"friendly_name": "Spare Room"}) == "Spare Room"
    assert model.room_name("climate.spare_room", {}) == "Spare Room"
