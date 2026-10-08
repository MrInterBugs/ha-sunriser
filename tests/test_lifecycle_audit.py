# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline regressions for reloads, rejected commands, and coordinator shutdown."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.maintenance import (
    MaintenancePlatform,
    setup_maintenance_entities,
)
from tests.conftest import DOMAIN, FAKE_CONFIG, FAKE_STATE
from tests.typing import collect_entities


@pytest.fixture
async def device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> AsyncIterator[SunRiserCoordinator]:
    coord = SunRiserCoordinator(hass, mock_config_entry)
    coord.config = {**FAKE_CONFIG, "factory_version": "1.006"}
    coord.data = deepcopy(FAKE_STATE)
    try:
        yield coord
    finally:
        await coord.async_close()


@pytest.mark.parametrize(
    "platform,suffix,changed",
    [
        ("number", "pwm_4_maintenance_level", {"pwm_count": 2}),
        ("switch", "pwm_4_maintenance_excluded", {"pwm_count": 2}),
        ("switch", "pwm_4_maintenance_output", {"pwm_count": 2}),
        ("number", "pwm_1_maintenance_level", {"pwm#1#onoff": True}),
        ("switch", "pwm_2_maintenance_output", {"pwm#2#onoff": False}),
        ("switch", "pwm_2_maintenance_excluded", {"pwm#2#color": ""}),
        ("switch", "blackout", {"factory_version": "1.005"}),
        ("number", "maintenance_timeout", {"factory_version": "1.005"}),
        ("sensor", "operating_mode", {"factory_version": "1.005"}),
        ("sensor", "maintenance_ends_at", {"factory_version": "1.005"}),
    ],
)
async def test_maintenance_cleanup_after_offline_changes(
    hass: HomeAssistant,
    device: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    platform: MaintenancePlatform,
    suffix: str,
    changed: dict[str, object],
) -> None:
    """A registry surviving reload must not retain controls that no longer apply."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    entry.runtime_data = device
    registry = entity_registry.async_get(hass)
    old = registry.async_get_or_create(
        platform, DOMAIN, f"{entry.entry_id}_{suffix}", config_entry=entry
    )
    unrelated = registry.async_get_or_create(
        platform, DOMAIN, f"{entry.entry_id}_pwm_4_fixed", config_entry=entry
    )
    other = MockConfigEntry(domain=DOMAIN, entry_id="other_controller")
    other.add_to_hass(hass)
    other_entity = registry.async_get_or_create(
        platform, DOMAIN, f"{other.entry_id}_{suffix}", config_entry=other
    )
    device.config.update(changed)
    added: list[Entity] = []
    setup_maintenance_entities(hass, entry, collect_entities(added), platform)
    assert registry.async_get(old.entity_id) is None
    assert registry.async_get(unrelated.entity_id) == unrelated
    assert registry.async_get(other_entity.entity_id) == other_entity


async def test_maintenance_failed_refresh_preserves_registry(
    hass: HomeAssistant,
    device: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    entry = mock_config_entry
    entry.add_to_hass(hass)
    entry.runtime_data = device
    registry = entity_registry.async_get(hass)
    old = registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{entry.entry_id}_pwm_4_maintenance_level",
        config_entry=entry,
    )
    old = registry.async_update_entity(
        old.entity_id, name="My maintenance level", disabled_by=None
    )
    added: list[Entity] = []
    setup_maintenance_entities(hass, entry, collect_entities(added), "number")
    device.last_update_success = False
    device.config["pwm_count"] = 2
    device.async_update_listeners()
    assert registry.async_get(old.entity_id) == old
    device.last_update_success = True
    device.async_update_listeners()
    assert registry.async_get(old.entity_id) is None


@pytest.mark.parametrize("failure", ["http", "timeout", "disconnect"])
async def test_failed_dst_enable_does_not_enable_tracking(
    device: SunRiserCoordinator, failure: str
) -> None:
    device.config["factory_version"] = "1.005"
    before = dict(device.config)
    with aioresponses() as http:
        if failure == "http":
            http.put(f"{device.base_url}/", status=500)
        else:
            http.put(
                f"{device.base_url}/",
                exception=(
                    TimeoutError()
                    if failure == "timeout"
                    else aiohttp.ClientConnectionError()
                ),
            )
        with pytest.raises((aiohttp.ClientError, TimeoutError)):
            await device.async_set_dst_auto_track(True)
    assert device.dst_auto_track is False
    assert device._last_known_dst is None
    assert device.config == before


async def test_queued_write_cannot_reopen_closed_coordinator(
    device: SunRiserCoordinator,
) -> None:
    """An old command waiting behind a read cannot execute after unload."""
    before = dict(device.config)
    started = asyncio.Event()

    async def write() -> None:
        started.set()
        await device.async_set_config({"pwm#1#fixed": 999})

    with aioresponses() as http:
        http.put(f"{device.base_url}/", status=200)
        async with device._config_lock:
            task = asyncio.create_task(write())
            await started.wait()
            assert not task.done()
            await device.async_close()
        with pytest.raises(HomeAssistantError, match="closed"):
            await task
        assert not http.requests
    assert device.config == before


@pytest.mark.parametrize("failure", ["http", "timeout", "disconnect"])
@pytest.mark.parametrize(
    "command", ["config", "pwm", "maintenance", "blackout", "timewarp"]
)
async def test_rejected_writes_keep_cached_state(
    device: SunRiserCoordinator, failure: str, command: str
) -> None:
    """Rejected commands publish no success and are not retried automatically."""
    before_config, before_state = deepcopy(device.config), deepcopy(device.data)
    listener = Mock()
    unsubscribe = device.async_add_listener(listener)
    refresh = AsyncMock()
    device.async_request_refresh = refresh
    commands: dict[str, Callable[[], Awaitable[None]]] = {
        "config": lambda: device.async_set_config({"pwm#1#fixed": 999}),
        "pwm": lambda: device.async_set_pwms({"1": 999}),
        "maintenance": lambda: device.async_set_service_mode(True),
        "blackout": lambda: device.async_set_blackout(True),
        "timewarp": lambda: device.async_set_timewarp(True),
    }
    url = f"{device.base_url}/" + ("" if command == "config" else "state")
    try:
        with aioresponses() as http:
            if failure == "http":
                http.put(url, status=500)
            else:
                http.put(
                    url,
                    exception=(
                        TimeoutError()
                        if failure == "timeout"
                        else aiohttp.ClientConnectionError()
                    ),
                )
            with pytest.raises((aiohttp.ClientError, TimeoutError)):
                await commands[command]()
            assert sum(len(requests) for requests in http.requests.values()) == 1
        assert device.config == before_config
        assert device.data == before_state
        listener.assert_not_called()
        refresh.assert_not_awaited()
    finally:
        unsubscribe()


async def test_reloads_remove_old_listeners_and_preserve_retained_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Exercise real HA platform unload/reload with a changed controller config."""
    from unittest.mock import patch

    entry = mock_config_entry
    entry.add_to_hass(hass)
    config = {**FAKE_CONFIG, "factory_version": "1.006"}

    def read_config(keys: list[str]) -> dict[str, object]:
        return dict(config)

    with (
        patch.object(
            SunRiserCoordinator,
            "async_get_config",
            new=AsyncMock(side_effect=read_config),
        ),
        patch.object(
            SunRiserCoordinator,
            "async_get_state",
            new=AsyncMock(return_value=FAKE_STATE),
        ) as state,
        patch.object(
            SunRiserCoordinator, "async_get_weather", new=AsyncMock(return_value=[])
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = entity_registry.async_get(hass)
        timeout_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{entry.entry_id}_maintenance_timeout"
        )
        assert timeout_id is not None
        registry.async_update_entity(timeout_id, name="My timeout", disabled_by=None)
        obsolete_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{entry.entry_id}_pwm_4_maintenance_level"
        )
        assert obsolete_id is not None
        config["pwm_count"] = 2
        config["pwm#1#onoff"] = True
        for _ in range(3):
            old: SunRiserCoordinator = entry.runtime_data
            assert old._listeners
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert not old._listeners
            before = state.await_count
            await old.async_refresh()
            assert state.await_count == before
            assert registry.async_get(obsolete_id) is None
            retained = registry.async_get(timeout_id)
            assert (
                retained is not None
                and retained.name == "My timeout"
                and retained.disabled_by is None
            )
            assert (
                registry.async_get_entity_id(
                    "switch", DOMAIN, f"{entry.entry_id}_pwm_1_maintenance_output"
                )
                is not None
            )
            assert (
                registry.async_get_entity_id(
                    "number", DOMAIN, f"{entry.entry_id}_pwm_1_maintenance_level"
                )
                is None
            )
        current: SunRiserCoordinator = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not current._listeners


async def test_unload_cancels_active_poll(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """HA-owned polling must stop before a reloaded coordinator starts polling."""
    from unittest.mock import patch

    entry = mock_config_entry
    entry.add_to_hass(hass)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_state() -> dict[str, object]:
        entered.set()
        await release.wait()
        return dict(FAKE_STATE)

    with (
        patch.object(
            SunRiserCoordinator,
            "async_get_config",
            new=AsyncMock(return_value=FAKE_CONFIG),
        ),
        patch.object(
            SunRiserCoordinator,
            "async_get_state",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
        patch.object(
            SunRiserCoordinator, "async_get_weather", new=AsyncMock(return_value=[])
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coord: SunRiserCoordinator = entry.runtime_data
        coord.async_get_state = blocked_state
        weather = AsyncMock(return_value=[])
        coord.async_get_weather = weather
        task = entry.async_create_background_task(
            hass, coord.async_refresh(), "test pending poll"
        )
        try:
            await entered.wait()
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert task.cancelled()
            weather.assert_not_awaited()
            assert not coord._listeners
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_unload_cancels_active_scheduled_reboot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A scheduled command is owned by the entry, just like its polling tasks."""
    from datetime import datetime
    from typing import cast
    from unittest.mock import patch

    from custom_components.sunriser.const import CONF_SCHEDULED_REBOOT

    entry = mock_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_SCHEDULED_REBOOT: True})
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def pending_reboot() -> None:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with (
        patch.object(
            SunRiserCoordinator,
            "async_get_config",
            new=AsyncMock(return_value=FAKE_CONFIG),
        ),
        patch.object(
            SunRiserCoordinator,
            "async_get_state",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
        patch.object(
            SunRiserCoordinator, "async_get_weather", new=AsyncMock(return_value=[])
        ),
        patch.object(
            SunRiserCoordinator,
            "async_reboot",
            new=AsyncMock(side_effect=pending_reboot),
        ),
        patch(
            "custom_components.sunriser.coordinator.async_track_time_change",
            return_value=lambda: None,
        ) as track,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        trigger = cast(Callable[[datetime], None], track.call_args.args[1])
        trigger(datetime(2026, 10, 8, 4))
        try:
            await entered.wait()
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert cancelled.is_set()
        finally:
            release.set()
            await hass.async_block_till_done()
