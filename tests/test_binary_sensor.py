# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for SunRiser binary_sensor platform (connectivity)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.binary_sensor import (
    SunRiserConnectivitySensor,
    async_setup_entry,
)
from custom_components.sunriser.coordinator import SunRiserCoordinator
from tests.conftest import ENTRY_ID
from tests.typing import collect_entities, require_value


def test_connectivity_sensor_unique_id(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sensor = SunRiserConnectivitySensor(coordinator, mock_config_entry)
    assert sensor.unique_id == f"{ENTRY_ID}_connectivity"


def test_connectivity_sensor_name(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sensor = SunRiserConnectivitySensor(coordinator, mock_config_entry)
    assert sensor._attr_translation_key == "connectivity"


def test_connectivity_sensor_is_on_when_ok_true(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.data = {**require_value(coordinator.data), "ok": True}
    sensor = SunRiserConnectivitySensor(coordinator, mock_config_entry)
    assert sensor.is_on is True


def test_connectivity_sensor_is_off_when_ok_false(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.data = {**require_value(coordinator.data), "ok": False}
    sensor = SunRiserConnectivitySensor(coordinator, mock_config_entry)
    assert sensor.is_on is False


def test_connectivity_sensor_is_off_when_no_data(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    coordinator.data = None
    sensor = SunRiserConnectivitySensor(coordinator, mock_config_entry)
    assert sensor.is_on is False


async def test_setup_creates_connectivity_sensor(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.runtime_data = coordinator
    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))
    assert len(added) == 1
    assert isinstance(added[0], SunRiserConnectivitySensor)
