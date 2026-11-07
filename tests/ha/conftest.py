"""Make this repo's custom_components visible to the Home Assistant test harness.

pytest-homeassistant-custom-component ships its own `custom_components` package, which shadows the repo's. Extending its
__path__ lets Home Assistant find wiser_predictive. Without the harness installed this file does nothing.
"""
import pathlib

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

import custom_components  # noqa: E402

_repo = str(pathlib.Path(__file__).resolve().parents[2] / "custom_components")
if _repo not in list(custom_components.__path__):
    custom_components.__path__.append(_repo)
