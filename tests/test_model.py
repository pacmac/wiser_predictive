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
