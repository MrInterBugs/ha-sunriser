# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures for SunRiser HA integration unit tests."""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Point hass at our project root so it finds custom_components/sunriser/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def hass_config_dir():
    return _PROJECT_ROOT


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow HA to load custom integrations from custom_components/ in this repo."""


from custom_components.sunriser.const import DEFAULT_PORT, DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator

ENTRY_ID = "test_entry_id"
HOST = "192.168.0.99"

# Fake config matching what async_load_device_config populates
FAKE_CONFIG = {
    "hostname": "testunit",
    "save_version": "1.005",
    "factory_version": "1.005",
    "model": "SunRiser 10",
    "pwm_count": 4,
    # pwm1 = dimmable light, dayplanner
    "pwm#1#color": "4500k",
    "pwm#1#onoff": False,
    "pwm#1#max": None,
    "pwm#1#manager": 1,
    "pwm#1#fixed": 500,
    # pwm2 = on/off switch (pump), no manager
    "pwm#2#color": "pump",
    "pwm#2#onoff": True,
    "pwm#2#max": None,
    "pwm#2#manager": 0,
    "pwm#2#fixed": None,
    # pwm3 = unused (empty color)
    "pwm#3#color": "",
    "pwm#3#onoff": False,
    "pwm#3#max": None,
    "pwm#3#manager": 0,
    "pwm#3#fixed": None,
    # pwm4 = dimmable light, weekplanner
    "pwm#4#color": "6500k",
    "pwm#4#onoff": False,
    "pwm#4#max": None,
    "pwm#4#manager": 2,
    "pwm#4#fixed": 0,
    # DS1820 temp sensor
    "sensors#sensor#AABBCCDDEEFF#name": "Water Temp",
    "sensors#sensor#AABBCCDDEEFF#unit": 1,
    "sensors#sensor#AABBCCDDEEFF#unitcomma": 1,
}

# Fake state matching what /state returns
FAKE_STATE = {
    "pwms": {"1": 500, "2": 1000, "3": 0, "4": 0},
    "uptime": 12345,
    "service_mode": 0,
    "sensors": {"AABBCCDDEEFF": [1, 211]},
}


@pytest.fixture
def mock_config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id=f"{HOST}:{DEFAULT_PORT}",
        data={
            CONF_HOST: HOST,
            CONF_PORT: DEFAULT_PORT,
            CONF_PASSWORD: None,
        },
        options={},
    )


@pytest.fixture(autouse=True)
def mock_http_frontend(hass):
    """Mock the HTTP static-path registration and add_extra_js_url called by
    async_setup so all tests that trigger component load don't need a real
    HTTP server."""
    from unittest.mock import (
        AsyncMock as _AsyncMock,
        MagicMock as _MagicMock,
        patch as _patch,
    )

    mock_http = _MagicMock()
    mock_http.async_register_static_paths = _AsyncMock()
    hass.http = mock_http
    with _patch("custom_components.sunriser.add_extra_js_url"):
        yield mock_http


@pytest.fixture
def coordinator(hass, mock_config_entry):
    """Real SunRiserCoordinator pre-populated with fake data; network calls mocked."""
    coord = SunRiserCoordinator(hass, mock_config_entry)
    coord.config = dict(FAKE_CONFIG)
    # Provide initial data so entities don't start unavailable
    coord.data = dict(FAKE_STATE)
    # Prevent any real HTTP during property/action tests
    coord.async_set_pwms = AsyncMock()
    coord.async_set_service_mode = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    coord.async_set_config = AsyncMock()
    return coord
