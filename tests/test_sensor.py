# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser sensor platform."""

from homeassistant.const import UnitOfTemperature

from tests.conftest import DOMAIN, ENTRY_ID, FAKE_STATE
from custom_components.sunriser.sensor import (
    SunRiserFirmwareSensor,
    SunRiserHostnameSensor,
    SunRiserTemperatureSensor,
    SunRiserUptimeSensor,
    SunRiserWeatherSensor,
    async_setup_entry,
)

# ---------------------------------------------------------------------------
# async_setup_entry — entity creation
# ---------------------------------------------------------------------------


async def test_setup_creates_diagnostic_sensors(hass, coordinator, mock_config_entry):
    hass.data.setdefault(DOMAIN, {})[ENTRY_ID] = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    types = {type(e).__name__ for e in added}
    assert "SunRiserUptimeSensor" in types
    assert "SunRiserFirmwareSensor" in types
    assert "SunRiserHostnameSensor" in types
    assert "SunRiserWeatherSensor" in types


async def test_setup_creates_temperature_sensor_for_ds1820(
    hass, coordinator, mock_config_entry
):
    hass.data.setdefault(DOMAIN, {})[ENTRY_ID] = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    assert len(temp_sensors) == 1
    assert temp_sensors[0]._rom == "AABBCCDDEEFF"


async def test_setup_skips_non_ds1820_sensors(hass, coordinator, mock_config_entry):
    """Device type 2 (not DS1820) should not create a temperature sensor."""
    coordinator.data = {**FAKE_STATE, "sensors": {"FFEEDD": [2, 500]}}
    hass.data.setdefault(DOMAIN, {})[ENTRY_ID] = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    assert len(temp_sensors) == 0


async def test_setup_no_sensors(hass, coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "sensors": {}}
    hass.data.setdefault(DOMAIN, {})[ENTRY_ID] = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    assert len(temp_sensors) == 0


async def test_setup_when_coordinator_data_none(hass, coordinator, mock_config_entry):
    coordinator.data = None
    hass.data.setdefault(DOMAIN, {})[ENTRY_ID] = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    weather_sensors = [e for e in added if isinstance(e, SunRiserWeatherSensor)]

    # Only diagnostic sensors, no temperature sensors.
    assert len(added) == 4
    assert len(temp_sensors) == 0
    assert len(weather_sensors) == 1


# ---------------------------------------------------------------------------
# SunRiserUptimeSensor
# ---------------------------------------------------------------------------


def test_uptime_value(coordinator):
    sensor = SunRiserUptimeSensor(coordinator)
    assert sensor.native_value == 12345


def test_uptime_none_when_no_data(coordinator):
    coordinator.data = None
    sensor = SunRiserUptimeSensor(coordinator)
    assert sensor.native_value is None


def test_uptime_unique_id(coordinator):
    sensor = SunRiserUptimeSensor(coordinator)
    assert sensor.unique_id == f"{ENTRY_ID}_uptime"


# ---------------------------------------------------------------------------
# SunRiserFirmwareSensor
# ---------------------------------------------------------------------------


def test_firmware_value(coordinator):
    sensor = SunRiserFirmwareSensor(coordinator)
    assert sensor.native_value == "1.005"


def test_firmware_none_when_save_version_missing(coordinator):
    coordinator.config["save_version"] = None
    sensor = SunRiserFirmwareSensor(coordinator)
    assert sensor.native_value is None


def test_firmware_unique_id(coordinator):
    sensor = SunRiserFirmwareSensor(coordinator)
    assert sensor.unique_id == f"{ENTRY_ID}_firmware"


# ---------------------------------------------------------------------------
# SunRiserHostnameSensor
# ---------------------------------------------------------------------------


def test_hostname_value(coordinator):
    sensor = SunRiserHostnameSensor(coordinator)
    assert sensor.native_value == "testunit"


def test_hostname_none_when_missing(coordinator):
    coordinator.config["hostname"] = None
    sensor = SunRiserHostnameSensor(coordinator)
    assert sensor.native_value is None


def test_hostname_unique_id(coordinator):
    sensor = SunRiserHostnameSensor(coordinator)
    assert sensor.unique_id == f"{ENTRY_ID}_hostname"


# ---------------------------------------------------------------------------
# SunRiserTemperatureSensor
# ---------------------------------------------------------------------------


def _make_temp_sensor(coordinator, mock_config_entry, rom="AABBCCDDEEFF"):
    return SunRiserTemperatureSensor(coordinator, mock_config_entry, rom)


def test_temperature_value_celsius(coordinator, mock_config_entry):
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert abs(sensor.native_value - 21.1) < 0.01


def test_temperature_unit_celsius(coordinator, mock_config_entry):
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS


def test_temperature_unit_raw_when_unit_not_celsius(coordinator, mock_config_entry):
    coordinator.config["sensors#sensor#AABBCCDDEEFF#unit"] = 0
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.native_unit_of_measurement == "raw"


def test_temperature_none_when_no_data(coordinator, mock_config_entry):
    coordinator.data = None
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.native_value is None


def test_temperature_unique_id(coordinator, mock_config_entry):
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.unique_id == f"{ENTRY_ID}_sensor_AABBCCDDEEFF"


def test_temperature_name_from_config(coordinator, mock_config_entry):
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor._attr_name == "Water Temp"


# ---------------------------------------------------------------------------
# SunRiserWeatherSensor
# ---------------------------------------------------------------------------


def _make_weather_sensor(coordinator):
    return SunRiserWeatherSensor(coordinator)


def test_weather_none_when_no_data(coordinator):
    coordinator.data = None
    sensor = _make_weather_sensor(coordinator)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_weather_none_when_no_channels(coordinator):
    coordinator.data = {**FAKE_STATE, "weather": []}
    sensor = _make_weather_sensor(coordinator)
    assert sensor.native_value is None


def test_weather_counts_active_channels(coordinator):
    coordinator.data = {
        **FAKE_STATE,
        "weather": [
            None,
            {"weather_program_id": 1},
            {"weather_program_id": 3, "moon_state": 2},
        ],
    }
    sensor = _make_weather_sensor(coordinator)
    assert sensor.native_value == 2


def test_weather_attributes_include_only_active_channels(coordinator):
    ch2 = {"weather_program_id": 1, "clouds_state": 0}
    ch3 = {"weather_program_id": 3, "moon_state": 2}
    coordinator.data = {**FAKE_STATE, "weather": [None, ch2, ch3]}
    sensor = _make_weather_sensor(coordinator)

    assert sensor.extra_state_attributes == {
        "channel_2": ch2,
        "channel_3": ch3,
    }
