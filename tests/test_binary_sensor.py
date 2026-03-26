# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for SunRiser binary_sensor platform (connectivity)."""

from tests.conftest import DOMAIN, ENTRY_ID
from custom_components.sunriser.binary_sensor import (
    SunRiserConnectivitySensor,
    async_setup_entry,
)


class _FakeEntry:
    entry_id = ENTRY_ID


def test_connectivity_sensor_unique_id(coordinator):
    sensor = SunRiserConnectivitySensor(coordinator, _FakeEntry())
    assert sensor.unique_id == f"{ENTRY_ID}_connectivity"


def test_connectivity_sensor_name(coordinator):
    sensor = SunRiserConnectivitySensor(coordinator, _FakeEntry())
    assert sensor.name == "Connectivity"


def test_connectivity_sensor_is_on_when_ok_true(coordinator):
    coordinator.data = {**coordinator.data, "ok": True}
    sensor = SunRiserConnectivitySensor(coordinator, _FakeEntry())
    assert sensor.is_on is True


def test_connectivity_sensor_is_off_when_ok_false(coordinator):
    coordinator.data = {**coordinator.data, "ok": False}
    sensor = SunRiserConnectivitySensor(coordinator, _FakeEntry())
    assert sensor.is_on is False


def test_connectivity_sensor_is_off_when_no_data(coordinator):
    coordinator.data = None
    sensor = SunRiserConnectivitySensor(coordinator, _FakeEntry())
    assert sensor.is_on is False


async def test_setup_creates_connectivity_sensor(hass, coordinator, mock_config_entry):
    mock_config_entry.runtime_data = coordinator
    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))
    assert len(added) == 1
    assert isinstance(added[0], SunRiserConnectivitySensor)
