# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser sensor platform."""

from datetime import datetime

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.sensor import (
    SunRiserFirmwareSensor,
    SunRiserHostnameSensor,
    SunRiserTemperatureSensor,
    SunRiserUptimeSensor,
    SunRiserWeatherChannelSensor,
    async_setup_entry,
)
from tests.conftest import ENTRY_ID, FAKE_STATE
from tests.typing import collect_entities, require_value

# ---------------------------------------------------------------------------
# async_setup_entry — entity creation
# ---------------------------------------------------------------------------


async def test_setup_creates_diagnostic_sensors(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    types = {type(e).__name__ for e in added}
    assert "SunRiserUptimeSensor" in types
    assert "SunRiserFirmwareSensor" in types
    assert "SunRiserHostnameSensor" in types


async def test_setup_creates_weather_channel_sensors(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.data = {
        **require_value(coordinator.data),
        "weather": [None, {"weather_program_id": 2}, {"weather_program_id": 5}],
    }
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    weather = [e for e in added if isinstance(e, SunRiserWeatherChannelSensor)]
    assert len(weather) == 2
    assert weather[0]._channel == 2
    assert weather[1]._channel == 3


async def test_setup_creates_temperature_sensor_for_ds1820(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    assert len(temp_sensors) == 1
    assert temp_sensors[0]._rom == "AABBCCDDEEFF"


async def test_setup_skips_non_ds1820_sensors(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Device type 2 (not DS1820) should not create a temperature sensor."""
    coordinator.data = {**FAKE_STATE, "sensors": {"FFEEDD": [2, 500]}}
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    assert len(temp_sensors) == 0


async def test_setup_no_sensors(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.data = {**FAKE_STATE, "sensors": {}}
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    assert len(temp_sensors) == 0


async def test_setup_when_coordinator_data_none(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.data = None
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    temp_sensors = [e for e in added if isinstance(e, SunRiserTemperatureSensor)]
    weather_sensors = [e for e in added if isinstance(e, SunRiserWeatherChannelSensor)]

    # Only the three diagnostic sensors; no temp or weather channel sensors.
    assert len(added) == 3
    assert len(temp_sensors) == 0
    assert len(weather_sensors) == 0


# ---------------------------------------------------------------------------
# SunRiserUptimeSensor
# ---------------------------------------------------------------------------


def test_uptime_value(coordinator: SunRiserCoordinator) -> None:
    sensor = SunRiserUptimeSensor(coordinator)
    assert sensor.native_value == 12345


def test_uptime_none_when_no_data(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = None
    sensor = SunRiserUptimeSensor(coordinator)
    assert sensor.native_value is None


def test_uptime_unique_id(coordinator: SunRiserCoordinator) -> None:
    sensor = SunRiserUptimeSensor(coordinator)
    assert sensor.unique_id == f"{ENTRY_ID}_uptime"


# ---------------------------------------------------------------------------
# SunRiserFirmwareSensor
# ---------------------------------------------------------------------------


def test_firmware_value(coordinator: SunRiserCoordinator) -> None:
    sensor = SunRiserFirmwareSensor(coordinator)
    assert sensor.native_value == "1.005"


def test_firmware_none_when_factory_version_missing(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.config["factory_version"] = None
    sensor = SunRiserFirmwareSensor(coordinator)
    assert sensor.native_value is None


def test_firmware_unique_id(coordinator: SunRiserCoordinator) -> None:
    sensor = SunRiserFirmwareSensor(coordinator)
    assert sensor.unique_id == f"{ENTRY_ID}_firmware"


# ---------------------------------------------------------------------------
# SunRiserHostnameSensor
# ---------------------------------------------------------------------------


def test_hostname_value(coordinator: SunRiserCoordinator) -> None:
    sensor = SunRiserHostnameSensor(coordinator)
    assert sensor.native_value == "testunit"


def test_hostname_none_when_missing(coordinator: SunRiserCoordinator) -> None:
    coordinator.config["hostname"] = None
    sensor = SunRiserHostnameSensor(coordinator)
    assert sensor.native_value is None


def test_hostname_unique_id(coordinator: SunRiserCoordinator) -> None:
    sensor = SunRiserHostnameSensor(coordinator)
    assert sensor.unique_id == f"{ENTRY_ID}_hostname"


# ---------------------------------------------------------------------------
# SunRiserTemperatureSensor
# ---------------------------------------------------------------------------


def _make_temp_sensor(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    rom: str = "AABBCCDDEEFF",
) -> SunRiserTemperatureSensor:
    return SunRiserTemperatureSensor(coordinator, mock_config_entry, rom)


def test_temperature_value_celsius(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert abs(require_value(sensor.native_value) - 21.1) < 0.01


def test_temperature_unit_celsius(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS


def test_temperature_unit_raw_when_unit_not_celsius(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    coordinator.config["sensors#sensor#AABBCCDDEEFF#unit"] = 0
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.native_unit_of_measurement is None
    assert sensor.device_class is None


def test_temperature_none_when_no_data(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    coordinator.data = None
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.native_value is None


def test_temperature_unique_id(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor.unique_id == f"{ENTRY_ID}_sensor_AABBCCDDEEFF"


def test_temperature_name_from_config(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sensor = _make_temp_sensor(coordinator, mock_config_entry)
    assert sensor._attr_name == "Water Temp"


# ---------------------------------------------------------------------------
# SunRiserWeatherChannelSensor
# ---------------------------------------------------------------------------


def _make_weather_channel_sensor(
    coordinator: SunRiserCoordinator, channel: int = 1
) -> SunRiserWeatherChannelSensor:
    return SunRiserWeatherChannelSensor(coordinator, channel)


def test_weather_channel_value_cloudy(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 3, "clouds_state": 1}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.native_value == "cloudy"


def test_weather_channel_value_thunder(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "thunder_state": 2, "clouds_state": 1}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.native_value == "thunder"


def test_weather_channel_value_rain(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "rainmins": 15, "clouds_state": 0}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.native_value == "rain"


def test_weather_channel_value_moon(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "moon_state": 1}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.native_value == "moon"


def test_weather_channel_value_clear(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.native_value == "clear"


def test_weather_channel_none_when_no_data(coordinator: SunRiserCoordinator) -> None:
    coordinator.data = None
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_weather_channel_none_when_index_out_of_range(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.data = {**FAKE_STATE, "weather": [{"weather_program_id": 1}]}
    sensor = _make_weather_channel_sensor(coordinator, channel=5)
    assert sensor.native_value is None


def test_weather_channel_attributes_include_program_id_and_name(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 2, "clouds_state": 0, "moon_state": 1}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    attrs = sensor.extra_state_attributes
    assert attrs["weather_program_id"] == 2
    assert attrs["weather_program_name"] is None  # not loaded in this fixture
    assert "clouds_state" not in attrs
    assert "moon_state" not in attrs
    assert attrs["clouds_active"] is False
    assert attrs["moon_active"] is True


def test_weather_channel_active_fields_absent_when_subsystem_not_configured(
    coordinator: SunRiserCoordinator,
) -> None:
    # Firmware only writes state fields for subsystems present in the program.
    # When absent, no *_active attribute should appear.
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "clouds_state": 0, "cloudticks": 5}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    attrs = sensor.extra_state_attributes
    assert "clouds_active" in attrs
    assert "thunder_active" not in attrs
    assert "moon_active" not in attrs
    assert "rain_active" not in attrs


def test_weather_channel_tick_nonzero_produces_datetime(
    coordinator: SunRiserCoordinator,
) -> None:
    # uptime = 12345 s = 12_345_000 ms; tick at 13_345_000 ms = 1000 s in the future
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "moon_next_state_tick": 13_345_000}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    attrs = sensor.extra_state_attributes
    assert "moon_next_change_at" in attrs
    assert attrs["moon_next_change_at"] is not None
    # Should be an ISO datetime string approximately 1000 s from now

    dt = datetime.fromisoformat(attrs["moon_next_change_at"])
    assert dt.tzinfo is not None


def test_weather_channel_tick_zero_produces_label(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "moon_next_state_tick": 0}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.extra_state_attributes["moon_next_change_at"] == "no moon tonight"


def test_weather_channel_tick_zero_clouds_label(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.data = {
        **FAKE_STATE,
        "weather": [
            {"weather_program_id": 1, "cloudticks": 0, "clouds_next_state_tick": 0}
        ],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    assert sensor.extra_state_attributes["clouds_next_change_at"] == "no clouds today"


def test_weather_channel_unique_id(coordinator: SunRiserCoordinator) -> None:
    sensor = _make_weather_channel_sensor(coordinator, channel=3)
    assert sensor.unique_id == f"{ENTRY_ID}_weather_3"


def test_weather_channel_name(coordinator: SunRiserCoordinator) -> None:
    # Channel name is passed as a translation placeholder so HA can localise the suffix.
    # FAKE_CONFIG has pwm#2#color = "pump" → COLOR_NAMES maps "pump" to "Mini Pump".
    sensor = _make_weather_channel_sensor(coordinator, channel=2)
    assert sensor._attr_translation_key == "weather_channel"
    assert sensor._attr_translation_placeholders == {"channel": "Mini Pump"}


def test_weather_channel_attributes_rename_passthrough(
    coordinator: SunRiserCoordinator,
) -> None:
    # cloudticks → cloud_ticks and rainmins → rain_duration_mins are renamed.
    coordinator.data = {
        **FAKE_STATE,
        "weather": [{"weather_program_id": 1, "cloudticks": 5000, "rainmins": 10}],
    }
    sensor = _make_weather_channel_sensor(coordinator, channel=1)
    attrs = sensor.extra_state_attributes
    assert attrs["cloud_ticks"] == 5000
    assert attrs["rain_duration_mins"] == 10
    assert "cloudticks" not in attrs
    assert "rainmins" not in attrs
