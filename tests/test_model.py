"""model.py: the room minimum and the margin above it. Values are the live ones read from the box 2026-11-07."""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "wiser_predictive" / "model.py"
_s = importlib.util.spec_from_file_location("model", _p)
model = importlib.util.module_from_spec(_s)
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
