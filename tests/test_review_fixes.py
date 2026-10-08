"""Regression tests for lifecycle, polling health, DST, and dynamic channels."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.light import async_setup_entry as setup_lights
from custom_components.sunriser.sensor import (
    async_setup_entry as setup_sensors,
    SunRiserWeatherChannelSensor,
)


async def test_offline_device_stays_unavailable_on_failed_config_tick(coordinator):
    coordinator.async_get_state = AsyncMock(side_effect=aiohttp.ClientConnectionError())
    coordinator.async_get_config = AsyncMock(
        side_effect=aiohttp.ClientConnectionError()
    )
    for _ in range(3):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    await coordinator.async_refresh()
    assert coordinator._consecutive_failures == 4
    assert (
        coordinator.last_update_success is False
    ), "Failed config tick falsely restores availability"
    coordinator.async_get_config.assert_not_awaited()
    coordinator.async_get_state = AsyncMock(return_value={"uptime": 42})
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data["ok"] is True


async def test_failed_dst_write_does_not_starve_state_polls(coordinator):
    coordinator.async_get_config = AsyncMock(return_value={})
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.config["factory_version"] = "1.005"
    coordinator._dst_auto_track = True

    coordinator.async_set_config = AsyncMock(
        side_effect=aiohttp.ClientConnectionError()
    )
    coordinator.async_get_state = AsyncMock(return_value={"uptime": 12346})
    for _ in range(10):
        await coordinator.async_refresh()
    assert (
        coordinator.async_get_state.await_count > 0
    ), "DST retry must allow state polling"
    assert (
        coordinator.async_get_state.await_count
        == coordinator.async_set_config.await_count
    )


async def test_dst_retry_observes_offline_controller(coordinator):
    coordinator.async_get_config = AsyncMock(return_value={})
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator._dst_auto_track = True

    coordinator.async_set_config = AsyncMock(side_effect=TimeoutError())
    coordinator.async_get_state = AsyncMock(side_effect=aiohttp.ClientConnectionError())
    for _ in range(4):
        await coordinator.async_refresh()
    coordinator.async_set_config.assert_not_awaited()
    assert coordinator.async_get_state.await_count == 4
    assert coordinator.last_update_success is False


async def test_dst_retry_clears_after_success(coordinator):
    coordinator.async_get_config = AsyncMock(return_value={})
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator._dst_auto_track = True

    coordinator.async_set_config = AsyncMock(
        side_effect=[aiohttp.ClientConnectionError(), None]
    )
    coordinator.async_get_state = AsyncMock(return_value={"uptime": 42})
    for _ in range(3):
        await coordinator.async_refresh()
    assert coordinator.async_set_config.await_count == 2
    assert coordinator.async_get_state.await_count == 3

    assert coordinator._last_known_dst is not None


async def test_stale_dst_retry_after_disable_does_not_write(coordinator):
    coordinator._dst_auto_track = False

    await coordinator._async_sync_dst()
    coordinator.async_set_config.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [aiohttp.ClientConnectionError(), RuntimeError(), asyncio.CancelledError()],
)
async def test_setup_failure_closes_session_and_reboot_callback(
    hass, mock_config_entry, failure
):
    """Cleanup also covers exceptions and cancellation before first refresh."""
    from custom_components.sunriser import async_setup_entry
    from homeassistant.exceptions import ConfigEntryNotReady

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"scheduled_reboot": True}
    )
    cancel = MagicMock()
    created = []

    async def fail(coord):
        created.append(coord)
        coord._get_session()
        raise failure

    with (
        patch(
            "custom_components.sunriser.coordinator.async_track_time_change",
            return_value=cancel,
        ),
        patch.object(SunRiserCoordinator, "async_load_device_config", fail),
    ):
        with pytest.raises((ConfigEntryNotReady, asyncio.CancelledError)):
            await async_setup_entry(hass, mock_config_entry)
    cancel.assert_called_once()
    assert created[0]._session.closed


async def test_disabling_dst_cancels_pending_write(coordinator):
    coordinator.async_get_config = AsyncMock(return_value={})
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator._dst_auto_track = True

    coordinator.async_get_state = AsyncMock(return_value={"uptime": 12346})
    await coordinator.async_set_dst_auto_track(False)
    await coordinator._async_update_data()
    coordinator.async_set_config.assert_not_awaited()


async def test_failed_setup_cancels_daily_reboot(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"scheduled_reboot": True}
    )
    cancel = MagicMock()
    with (
        patch(
            "custom_components.sunriser.coordinator.async_track_time_change",
            return_value=cancel,
        ),
        patch.object(
            SunRiserCoordinator,
            "async_get_config",
            side_effect=aiohttp.ClientConnectionError(),
        ),
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert result is False
    cancel.assert_called_once()


async def test_newly_active_channel_uses_current_type(
    hass, coordinator, mock_config_entry
):
    mock_config_entry.runtime_data = coordinator
    added = []
    await setup_lights(hass, mock_config_entry, lambda entities: added.extend(entities))
    remote = dict(coordinator.config)
    remote.update(
        {"pwm#3#color": "pump", "pwm#3#onoff": True, "pwm#3#name": "New pump"}
    )

    async def read(keys):
        return {key: remote.get(key) for key in keys}

    coordinator.async_get_config = AsyncMock(side_effect=read)
    await coordinator._async_refresh_config(coordinator.data)
    coordinator.async_set_updated_data(dict(coordinator.data))
    assert not any(e._pwm_num == 3 for e in added)
    assert coordinator.config["pwm#3#name"] == "New pump"
    assert coordinator.pwm_is_onoff(3)
    from custom_components.sunriser.switch import (
        async_setup_entry as setup_switches,
        SunRiserSwitch,
    )

    switches = []
    await setup_switches(
        hass, mock_config_entry, lambda entities: switches.extend(entities)
    )
    assert any(isinstance(e, SunRiserSwitch) and e._pwm_num == 3 for e in switches)


async def test_weather_sensor_recovers_after_initial_weather_failure(
    hass, coordinator, mock_config_entry
):
    mock_config_entry.runtime_data = coordinator
    coordinator.data["weather"] = []
    added = []
    await setup_sensors(
        hass, mock_config_entry, lambda entities: added.extend(entities)
    )
    coordinator.async_set_updated_data(
        {**coordinator.data, "weather": [{"weather_program_id": 1}]}
    )
    coordinator.async_set_updated_data(
        {**coordinator.data, "weather": [{"weather_program_id": 2}]}
    )
    weather = [e for e in added if isinstance(e, SunRiserWeatherChannelSensor)]
    assert len(weather) == 1
    assert weather[0]._channel == 1
