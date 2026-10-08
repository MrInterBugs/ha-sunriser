"""Regression coverage for firmware upgrades and interrupted initialization."""

from unittest.mock import AsyncMock

import aiohttp
import pytest
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.sunriser.const import DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.sensor import SunRiserFirmwareSensor
from custom_components.sunriser.switch import SunRiserDSTAutoSwitch, async_setup_entry


def test_firmware_uses_running_version(coordinator):
    coordinator.config.update(factory_version="1.006", save_version="1.005")
    assert coordinator.device_info["sw_version"] == "1.006"
    assert SunRiserFirmwareSensor(coordinator).native_value == "1.006"


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.005", False),
        ("1.006", True),
        ("1.010", True),
        ("2.000", True),
        (None, False),
        ("unknown", False),
    ],
)
def test_native_dst_version(coordinator, version, expected):
    coordinator.config["factory_version"] = version
    assert coordinator.firmware_handles_dst is expected


async def test_native_dst_never_writes_summertime(coordinator):
    coordinator.config["factory_version"] = "1.006"
    coordinator.async_set_config = AsyncMock()
    coordinator._dst_auto_track = True

    await coordinator.async_set_dst_auto_track(True)
    await coordinator._async_sync_dst()
    coordinator.async_set_config.assert_not_awaited()
    assert not coordinator._dst_auto_track


async def test_native_dst_removes_old_entity(hass, coordinator, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = coordinator
    coordinator.config["factory_version"] = "1.006"
    registry = entity_registry.async_get(hass)
    old = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{mock_config_entry.entry_id}_dst_auto_track",
        config_entry=mock_config_entry,
    )
    added = []
    await async_setup_entry(
        hass, mock_config_entry, lambda entities: added.extend(entities)
    )
    assert registry.async_get(old.entity_id) is None
    assert not any(isinstance(entity, SunRiserDSTAutoSwitch) for entity in added)


async def test_startup_clears_restored_dst_tracking(hass, mock_config_entry):
    """Reloading after an upgrade must not restore HA's old DST writer."""
    hass.data.setdefault(DOMAIN, {})[
        f"{mock_config_entry.entry_id}_dst_auto_track"
    ] = True
    coordinator = SunRiserCoordinator(hass, mock_config_entry)
    coordinator.async_get_config = AsyncMock(
        return_value={"factory_version": "1.006", "save_version": "1.005"}
    )
    coordinator.async_set_config = AsyncMock()

    try:
        assert coordinator._dst_auto_track
        await coordinator.async_load_device_config()

        assert coordinator.firmware_version == "1.006"
        assert not coordinator._dst_auto_track

        coordinator.async_get_config.assert_awaited_once_with(
            coordinator._BASE_CONFIG_KEYS
        )
        coordinator.async_set_config.assert_not_awaited()
    finally:
        await coordinator.async_close()


async def test_firmware_upgrade_retires_dst_entity_without_reload(
    hass, coordinator, mock_config_entry
):
    """A periodic firmware refresh removes only the obsolete DST control."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = coordinator
    registry = entity_registry.async_get(hass)
    old = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{mock_config_entry.entry_id}_dst_auto_track",
        config_entry=mock_config_entry,
    )
    maintenance = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{mock_config_entry.entry_id}_maintenance",
        config_entry=mock_config_entry,
    )
    added = []
    await async_setup_entry(
        hass, mock_config_entry, lambda entities: added.extend(entities)
    )
    assert any(isinstance(entity, SunRiserDSTAutoSwitch) for entity in added)
    assert registry.async_get(old.entity_id) is not None

    coordinator._dst_auto_track = True

    coordinator.async_get_config = AsyncMock(return_value={"factory_version": "1.006"})
    await coordinator._async_refresh_config(coordinator.data)
    coordinator.async_set_updated_data(dict(coordinator.data))

    assert registry.async_get(old.entity_id) is None
    assert registry.async_get(maintenance.entity_id) is not None
    assert not coordinator._dst_auto_track

    coordinator.async_set_config.assert_not_awaited()


async def test_failed_initial_config_is_retried_in_full(coordinator):
    coordinator.data = None
    coordinator.async_get_state = AsyncMock(return_value={"pwms": {"1": 0, "2": 0}})
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(
        side_effect=[
            aiohttp.ClientConnectionError(),
            {"pwm#1#name": "Light", "pwm#2#name": "Pump"},
        ]
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert coordinator.config["pwm#1#name"] == "Light"
    assert coordinator.config["pwm#2#name"] == "Pump"
    assert (
        coordinator.async_get_config.await_args_list[0]
        == coordinator.async_get_config.await_args_list[1]
    )


async def test_refresh_updates_registered_firmware(
    hass, coordinator, mock_config_entry
):
    mock_config_entry.add_to_hass(hass)
    registry = device_registry.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, **coordinator.device_info
    )
    coordinator.async_get_config = AsyncMock(return_value={"factory_version": "1.006"})
    coordinator._dst_auto_track = True
    await coordinator._async_refresh_config(coordinator.data)
    assert registry.async_get(device.id).sw_version == "1.006"
    assert not coordinator._dst_auto_track


async def test_failed_poll_does_not_mutate_published_data(coordinator):

    coordinator.data = {"ok": True, "uptime": 100}
    coordinator.async_get_state = AsyncMock(side_effect=aiohttp.ClientConnectionError())
    result = await coordinator._async_update_data()
    assert result["ok"] is False
    assert coordinator.data == {"ok": True, "uptime": 100}
