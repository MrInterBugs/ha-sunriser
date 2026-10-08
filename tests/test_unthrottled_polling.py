"""Behavioral coverage for the firmware 1.006 request simplification."""

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import msgpack
import pytest
from aioresponses import aioresponses
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from custom_components.sunriser.coordinator import SunRiserCoordinator
from tests.conftest import FAKE_CONFIG, FAKE_STATE


def pack(value):
    return msgpack.packb(value, use_bin_type=True)


async def test_setup_completes_all_reads_before_creating_entities(
    hass, mock_config_entry
):
    """No timers or staged callbacks are needed even for ten channels."""
    mock_config_entry.add_to_hass(hass)
    base = "http://192.168.0.99:80"
    config = {**FAKE_CONFIG, "factory_version": "1.006", "pwm_count": 10}
    state = {**FAKE_STATE, "pwms": {str(i): 0 for i in range(1, 11)}}
    weather = [{"weather_program_id": 7}]
    config["weather#setup#7#name"] = "Summer"
    with aioresponses() as http, patch.object(
        hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
    ) as forward:
        http.post(f"{base}/", body=pack(config))
        http.get(f"{base}/state", body=pack(state))
        http.get(f"{base}/weather", body=pack(weather))
        http.post(f"{base}/", body=pack(config))
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        coord = mock_config_entry.runtime_data
        forward.assert_awaited_once()
        assert coord.data["weather"] == weather
        assert coord.sensor_value("AABBCCDDEEFF") == 21.1
        assert coord.weather_program_name(7) == "Summer"
        posts = http.requests[("POST", URL(f"{base}/"))]
        assert len(posts) == 2  # base identity, then one complete config request
        keys = msgpack.unpackb(posts[1].kwargs["data"], raw=False)
        assert len(posts[1].kwargs["data"]) > 250
        assert "pwm#10#onoff" in keys
        assert "sensors#sensor#AABBCCDDEEFF#unitcomma" in keys
        assert "weather#setup#7#name" in keys
        assert coord._scheduled_reboot_cancel is None
        await coord.async_close()


async def test_large_config_read_is_one_http_request(coordinator):
    keys = [
        f"pwm#{channel}#{key}"
        for channel in range(1, 11)
        for key in ("color", "name", "onoff", "manager", "fixed", "max")
    ]
    expected = dict.fromkeys(keys, 1)
    try:
        with aioresponses() as http:
            http.post(f"{coordinator.base_url}/", body=pack(expected))
            assert await coordinator.async_get_config(keys) == expected
            requests = http.requests[("POST", URL(f"{coordinator.base_url}/"))]
            assert len(requests) == 1
            assert msgpack.unpackb(requests[0].kwargs["data"], raw=False) == keys
            assert len(requests[0].kwargs["data"]) > 250
        assert not coordinator._get_session().connector.force_close
    finally:
        await coordinator.async_close()


async def test_each_poll_updates_state_weather_and_config(coordinator):
    coordinator.async_get_state = AsyncMock(
        return_value={**FAKE_STATE, "uptime": 54321}
    )
    coordinator.async_get_weather = AsyncMock(return_value=[{"weather_program_id": 7}])
    coordinator.async_get_config = AsyncMock(
        return_value={
            "pwm#3#color": "pump",
            "pwm#3#onoff": True,
            "weather#setup#7#name": "Summer",
            "factory_version": "1.006",
        }
    )
    for _ in range(3):
        await coordinator.async_refresh()
        assert coordinator.data["uptime"] == 54321
        assert coordinator.data["ok"]
        assert coordinator.data["weather"] == [{"weather_program_id": 7}]
        assert coordinator.config["pwm#3#onoff"] is True
        assert coordinator.weather_program_name(7) == "Summer"
    assert coordinator.async_get_state.await_count == 3
    assert coordinator.async_get_weather.await_count == 3
    assert coordinator.async_get_config.await_count == 3


async def test_failed_state_does_not_make_auxiliary_requests(coordinator):
    coordinator.async_get_state = AsyncMock(side_effect=TimeoutError())
    coordinator.async_get_weather = AsyncMock()
    coordinator.async_get_config = AsyncMock()
    coordinator._dst_auto_track = True
    result = await coordinator._async_update_data()
    assert result["ok"] is False
    coordinator.async_get_weather.assert_not_awaited()
    coordinator.async_get_config.assert_not_awaited()
    coordinator.async_set_config.assert_not_awaited()


@pytest.mark.parametrize("initial", [False, True])
async def test_config_failure_preserves_cache_and_retries(coordinator, initial):
    old = dict(coordinator.config)
    if initial:
        coordinator.data = None
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(
        side_effect=[TimeoutError(), {"pwm#1#name": "Updated"}]
    )
    if initial:
        with pytest.raises(UpdateFailed, match="configuration"):
            await coordinator._async_update_data()
    else:
        assert (await coordinator._async_update_data())["ok"]
    assert coordinator.config == old
    result = await coordinator._async_update_data()
    assert result["ok"]
    assert coordinator.config["pwm#1#name"] == "Updated"
    assert (
        coordinator.async_get_config.await_args_list[0]
        == coordinator.async_get_config.await_args_list[1]
    )


@pytest.mark.parametrize(
    "weather_error", [TimeoutError(), aiohttp.ClientConnectionError()]
)
async def test_initial_weather_failure_recovers_next_poll(coordinator, weather_error):
    coordinator.data = None
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(
        side_effect=[weather_error, [{"weather_program_id": 7}]]
    )
    coordinator.async_get_config = AsyncMock(
        return_value={"weather#setup#7#name": "Summer"}
    )
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data["weather"] == []
    await coordinator.async_refresh()
    assert coordinator.data["weather"] == [{"weather_program_id": 7}]
    assert "weather#setup#7#name" in coordinator.async_get_config.await_args.args[0]


@pytest.mark.parametrize(
    "count,state_count,expected", [(None, 10, 10), (None, 0, 8), (4, 2, 4)]
)
async def test_channel_count_fallback(coordinator, count, state_count, expected):
    coordinator.config["pwm_count"] = count
    coordinator.async_get_config = AsyncMock(return_value={"pwm_count": count})
    await coordinator._async_refresh_config(
        {"pwms": {str(i): 0 for i in range(state_count)}}
    )
    assert coordinator.pwm_count == expected
    assert f"pwm#{expected}#onoff" in coordinator.async_get_config.await_args.args[0]


@pytest.mark.parametrize("status", [200, 500])
async def test_config_read_cannot_overwrite_concurrent_write(coordinator, status):
    """Pause a read while a real HTTP writer attempts to change the same key."""
    key = "pwm#1#manager"
    entered, release, write_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def read(keys):
        entered.set()
        await release.wait()
        return {key: 1}

    coordinator.async_get_config = AsyncMock(side_effect=read)
    coordinator.async_set_config = SunRiserCoordinator.async_set_config.__get__(
        coordinator
    )

    async def write():
        write_started.set()
        await coordinator.async_set_config({key: 3})

    try:
        with aioresponses() as http:
            http.put(f"{coordinator.base_url}/", status=status)
            read_task = asyncio.create_task(
                coordinator._async_refresh_config(FAKE_STATE)
            )
            await asyncio.wait_for(entered.wait(), 1)
            write_task = asyncio.create_task(write())
            await asyncio.wait_for(write_started.wait(), 1)
            assert not write_task.done()
            assert not http.requests
            release.set()
            await read_task
            if status == 500:
                with pytest.raises(aiohttp.ClientResponseError):
                    await write_task
            else:
                await write_task
        assert coordinator.config[key] == (3 if status == 200 else 1)
    finally:
        release.set()
        await coordinator.async_close()


async def test_native_dst_upgrade_prevents_legacy_write_in_same_poll(coordinator):
    coordinator._dst_auto_track = True
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(return_value={"factory_version": "1.006"})
    await coordinator.async_refresh()
    assert not coordinator._dst_auto_track
    coordinator.async_set_config.assert_not_awaited()


async def test_failed_config_read_does_not_sync_potentially_upgraded_firmware(
    coordinator,
):
    coordinator._dst_auto_track = True
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(side_effect=TimeoutError())
    await coordinator.async_refresh()
    coordinator.async_set_config.assert_not_awaited()


async def test_legacy_dst_changes_once_without_replacing_state_poll(coordinator):
    coordinator._dst_auto_track = True
    coordinator._last_known_dst = False
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(return_value={})
    with patch("custom_components.sunriser.coordinator.dt_util.now") as now:
        now.return_value.dst.return_value = True
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert coordinator.async_get_state.await_count == 2
    coordinator.async_set_config.assert_awaited_once_with({"summertime": 1})


async def test_scheduled_reboot_defaults_off(coordinator):
    assert coordinator._scheduled_reboot_cancel is None


@pytest.mark.parametrize(
    "options,expected",
    [
        ({}, False),
        ({"scheduled_reboot": True}, True),
        ({"scheduled_reboot": False}, False),
    ],
)
async def test_reboot_options_default_preserves_explicit_setting(
    hass, mock_config_entry, options, expected
):
    from custom_components.sunriser.config_flow import SunRiserOptionsFlow

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options=options)
    flow = SunRiserOptionsFlow(mock_config_entry)
    flow.hass = hass
    result = await flow.async_step_init()
    field = next(
        key for key in result["data_schema"].schema if str(key) == "scheduled_reboot"
    )
    assert field.default() is expected
