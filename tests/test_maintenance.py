# SPDX-License-Identifier: GPL-3.0-or-later
"""Maintenance protocol, lifecycle and user-facing behavior regressions."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import msgpack
import pytest
from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.maintenance import (
    MaintenancePlatform,
    SunRiserBlackoutSwitch,
    SunRiserMaintenanceConfigSwitch,
    SunRiserMaintenanceEndSensor,
    SunRiserMaintenanceNumber,
    SunRiserOperatingModeSensor,
    setup_maintenance_entities,
)
from custom_components.sunriser.switch import SunRiserMaintenanceSwitch
from tests.conftest import FAKE_CONFIG
from tests.typing import as_async_mock, collect_entities

FIXTURE: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures/maintenance_1006.json").read_text()
)


@pytest.fixture
async def device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> AsyncIterator[SunRiserCoordinator]:
    coord = SunRiserCoordinator(hass, mock_config_entry)
    coord.config = {**FAKE_CONFIG, **FIXTURE["config"]}
    coord.data = dict(FIXTURE["states"]["normal"])
    coord.async_request_refresh = AsyncMock()
    try:
        yield coord
    finally:
        await coord.async_close()


@pytest.mark.parametrize("enabled", [True, False])
async def test_blackout_wire_contract(
    device: SunRiserCoordinator, enabled: bool
) -> None:
    with aioresponses() as http:
        http.put(f"{device.base_url}/state", status=200)
        await device.async_set_blackout(enabled)
        request = http.requests[("PUT", URL(f"{device.base_url}/state"))][0]
        payload = msgpack.unpackb(request.kwargs["data"], raw=False)
        assert payload == {"blackout": int(enabled)}
        assert type(payload["blackout"]) is int
    as_async_mock(device.async_request_refresh).assert_awaited_once()
    assert (
        device.data == FIXTURE["states"]["normal"]
    )  # HTTP success is not state confirmation.


async def test_failed_write_is_not_retried_or_published(
    device: SunRiserCoordinator,
) -> None:
    with aioresponses() as http:
        http.put(f"{device.base_url}/state", exception=TimeoutError())
        with pytest.raises(TimeoutError):
            await device.async_set_blackout(True)
        assert len(http.requests[("PUT", URL(f"{device.base_url}/state"))]) == 1
    as_async_mock(device.async_request_refresh).assert_not_awaited()
    assert device.operating_mode == "normal"
    with aioresponses() as http:
        http.put(f"{device.base_url}/", status=500)
        with pytest.raises(aiohttp.ClientResponseError):
            await SunRiserMaintenanceNumber(device, 1).async_set_native_value(40)
    assert device.config["pwm#1#service"] == 65


@pytest.mark.parametrize("version", [None, "unknown", "1.005"])
async def test_unsupported_commands_fail_closed(
    device: SunRiserCoordinator, version: str | None
) -> None:
    device.config["factory_version"] = version
    for command in [
        device.async_set_blackout(True),
        device.async_set_maintenance_config("service_timeout", 30),
    ]:
        with pytest.raises(HomeAssistantError, match="1.006"):
            await command
    assert not SunRiserBlackoutSwitch(device).available


async def test_maintenance_switch_stops_blackout(
    device: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    device.data = dict(FIXTURE["states"]["blackout"])
    with aioresponses() as http:
        http.put(f"{device.base_url}/state", status=200)
        await SunRiserMaintenanceSwitch(device, mock_config_entry).async_turn_off()
        payload = msgpack.unpackb(
            http.requests[("PUT", URL(f"{device.base_url}/state"))][0].kwargs["data"],
            raw=False,
        )
        assert payload == {"service_mode": 0}
        assert type(payload["service_mode"]) is int
    as_async_mock(device.async_request_refresh).assert_awaited_once()


async def test_blackout_entity_commands(device: SunRiserCoordinator) -> None:
    device.async_set_blackout = AsyncMock()
    switch = SunRiserBlackoutSwitch(device)
    await switch.async_turn_on()
    await switch.async_turn_off()
    assert as_async_mock(device.async_set_blackout).await_args_list[0].args == (True,)
    assert as_async_mock(device.async_set_blackout).await_args_list[1].args == (False,)


@pytest.mark.parametrize(
    "state,expected",
    [
        ("normal", "normal"),
        ("maintenance", "maintenance"),
        ("blackout", "blackout"),
        ("indefinite", "maintenance"),
        ("time_lapse", "time_lapse"),
    ],
)
async def test_reported_modes_and_legacy_switch(
    device: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    state: str,
    expected: str,
) -> None:
    device.data = dict(FIXTURE["states"][state])
    assert SunRiserOperatingModeSensor(device).native_value == expected
    assert SunRiserBlackoutSwitch(device).is_on == (expected == "blackout")
    assert SunRiserMaintenanceSwitch(device, mock_config_entry).is_on == (
        expected in ("maintenance", "blackout")
    )


async def test_expiry_does_not_drift_on_failed_poll(
    device: SunRiserCoordinator,
) -> None:
    now = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
    device.async_get_state = AsyncMock(return_value=dict(FIXTURE["states"]["blackout"]))
    with patch(
        "custom_components.sunriser.coordinator.dt_util.utcnow", return_value=now
    ):
        device.data = await device._async_refresh_state()
    sensor = SunRiserMaintenanceEndSensor(device)
    assert sensor.native_value == now + timedelta(seconds=900)
    device.async_get_state = AsyncMock(side_effect=TimeoutError())
    device.data = await device._async_refresh_state()
    assert sensor.native_value == now + timedelta(seconds=900)
    # A subsequent successful read lacking optional fields must erase old state.
    device.async_get_state = AsyncMock(return_value={"service_mode": 0})
    device.data = await device._async_refresh_state()
    assert sensor.native_value is None
    assert "service_left" not in device.data and "blackout" not in device.data
    device.async_get_state = AsyncMock(return_value={"service_mode": 123})
    device.data = await device._async_refresh_state()
    assert device.operating_mode is None
    assert SunRiserBlackoutSwitch(device).is_on is None
    device.data = None
    assert device.operating_mode is None


@pytest.mark.parametrize(
    "remaining", [None, 0, -1, "unknown", float("nan"), float("inf")]
)
async def test_no_invented_end_time(
    device: SunRiserCoordinator, remaining: Any
) -> None:
    device.data = {"service_mode": 123, "service_left": remaining}
    device.data["_state_received_at"] = datetime.now(timezone.utc)
    assert device.maintenance_ends_at is None


async def test_number_defaults_and_config_writes(device: SunRiserCoordinator) -> None:
    timeout = SunRiserMaintenanceNumber(device)
    level = SunRiserMaintenanceNumber(device, 1)
    assert timeout.native_value == 30
    assert level.native_value == 65
    with aioresponses() as http:
        http.put(f"{device.base_url}/", status=200)
        await level.async_set_native_value(0)
        payload = msgpack.unpackb(
            http.requests[("PUT", URL(f"{device.base_url}/"))][0].kwargs["data"],
            raw=False,
        )
        assert payload == {"pwm#1#service": 0, "save_version": "1.006"}
    assert level.native_value == 0
    assert device.config["service_timeout"] == 30
    device.config.pop("pwm#1#service")
    assert level.native_value == 75
    device.config.pop("service_value")
    assert level.native_value == 100
    device.config.pop("service_timeout")
    assert timeout.native_value == 1440
    device.async_set_config = AsyncMock(side_effect=device.update_config_cache)
    for value in (0, 10080):
        await timeout.async_set_native_value(value)
        assert timeout.native_value == value
    for value in (-1, 10081, 0.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            await timeout.async_set_native_value(value)
    with pytest.raises(ValueError):
        await level.async_set_native_value(101)


@pytest.mark.parametrize("exclusion,on,off", [(True, True, False), (False, 100, 0)])
async def test_channel_switch_values(
    device: SunRiserCoordinator, exclusion: bool, on: bool | int, off: bool | int
) -> None:
    switch = SunRiserMaintenanceConfigSwitch(device, 2, exclusion=exclusion)
    key = f"pwm#2#{'nomaint' if exclusion else 'service'}"
    device.async_set_config = AsyncMock(side_effect=device.update_config_cache)
    await switch.async_turn_on()
    assert switch.is_on
    assert device.config[key] == on and type(device.config[key]) is type(on)
    await switch.async_turn_off()
    assert not switch.is_on
    assert device.config[key] == off and type(device.config[key]) is type(off)


@pytest.mark.parametrize(
    "platform,count", [("switch", 5), ("number", 3), ("sensor", 2)]
)
async def test_dynamic_platform_discovery(
    hass: HomeAssistant,
    device: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    platform: MaintenancePlatform,
    count: int,
) -> None:
    mock_config_entry.runtime_data = device
    added: list[Entity] = []
    device.config["factory_version"] = "1.005"
    setup_maintenance_entities(
        hass, mock_config_entry, collect_entities(added), platform
    )
    assert added == []
    device.config["factory_version"] = "1.006"
    device.async_update_listeners()
    assert len(added) == count
    assert all(entity.available for entity in added)
    assert len({entity.unique_id for entity in added}) == count
    device.async_update_listeners()
    assert len(added) == count  # no duplicates on normal poll
    device.config["pwm#1#onoff"] = True
    device.async_update_listeners()
    assert len(added) == count + (1 if platform == "switch" else 0)
    device.config["factory_version"] = "1.005"
    device.async_update_listeners()
    assert all(not entity.available for entity in added)


async def test_type_change_removes_obsolete_registry_entity(
    hass: HomeAssistant, device: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = device
    added: list[Entity] = []
    setup_maintenance_entities(
        hass, mock_config_entry, collect_entities(added), "number"
    )
    registry = entity_registry.async_get(hass)
    entry = registry.async_get_or_create(
        "number",
        "sunriser",
        f"{device.entry_id}_pwm_1_maintenance_level",
        config_entry=mock_config_entry,
    )
    device.config["pwm#1#onoff"] = True
    device.async_update_listeners()
    assert registry.async_get(entry.entity_id) is None


async def test_new_metadata_shares_bulk_read(device: SunRiserCoordinator) -> None:
    device.async_get_config = AsyncMock(return_value={})
    await device._async_refresh_config({"pwms": {}})
    calls = as_async_mock(device.async_get_config).await_args_list
    assert len(calls) == 1
    keys = calls[0].args[0]
    assert "service_timeout" in keys and "service_value" in keys
    assert all(
        f"pwm#{i}#service" in keys and f"pwm#{i}#nomaint" in keys for i in range(1, 5)
    )
    assert "pwm#5#service" not in keys


async def test_ha_setup_reload_and_external_changes(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Real HA platform registration, mode readback and no command replay on reload."""
    config = {**FAKE_CONFIG, **FIXTURE["config"]}
    state = dict(FIXTURE["states"]["blackout"])

    async def read_config(self: SunRiserCoordinator, keys: list[str]) -> dict[str, Any]:
        return {key: config.get(key) for key in keys}

    mock_config_entry.add_to_hass(hass)
    registry = entity_registry.async_get(hass)
    with (
        patch.object(SunRiserCoordinator, "async_get_config", read_config),
        patch.object(
            SunRiserCoordinator,
            "async_get_state",
            AsyncMock(side_effect=lambda: dict(state)),
        ),
        patch.object(
            SunRiserCoordinator, "async_get_weather", AsyncMock(return_value=[])
        ),
        patch.object(
            SunRiserCoordinator, "async_set_service_mode", AsyncMock()
        ) as maintenance_command,
        patch.object(
            SunRiserCoordinator, "async_set_blackout", AsyncMock()
        ) as blackout_command,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        def entity_id(platform: str, suffix: str) -> str:
            eid = registry.async_get_entity_id(
                platform, "sunriser", f"{mock_config_entry.entry_id}_{suffix}"
            )
            assert eid is not None
            return eid

        def state_of(platform: str, suffix: str) -> str:
            entity = hass.states.get(entity_id(platform, suffix))
            assert entity is not None
            return entity.state

        assert state_of("switch", "blackout") == "on"
        assert state_of("switch", "maintenance") == "on"
        assert state_of("sensor", "operating_mode") == "blackout"
        end_id = entity_id("sensor", "maintenance_ends_at")
        end_entry = registry.async_get(end_id)
        assert end_entry is not None
        assert (
            end_entry.disabled_by is entity_registry.RegistryEntryDisabler.INTEGRATION
        )
        assert hass.states.get(end_id) is None
        assert not hass.services.has_service("sunriser", "resume_normal_operation")
        assert (
            registry.async_get_entity_id(
                "button",
                "sunriser",
                f"{mock_config_entry.entry_id}_resume_normal_operation",
            )
            is None
        )
        # Explicitly enable the optional sensor; reload must preserve that choice.
        registry.async_update_entity(end_id, disabled_by=None)
        timeout_entry = registry.async_get(entity_id("number", "maintenance_timeout"))
        assert timeout_entry is not None and timeout_entry.disabled_by is not None
        assert (
            registry.async_get_entity_id(
                "number",
                "sunriser",
                f"{mock_config_entry.entry_id}_pwm_2_maintenance_level",
            )
            is None
        )
        assert entity_id("switch", "pwm_2_maintenance_output")

        # Reload reads the still-active controller session and never reissues it.
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert state_of("sensor", "operating_mode") == "blackout"
        assert state_of("sensor", "maintenance_ends_at") != "unknown"
        maintenance_command.assert_not_awaited()
        blackout_command.assert_not_awaited()
        coord: SunRiserCoordinator = mock_config_entry.runtime_data
        # Physical-button change to maintenance, then controller-owned expiry.
        state.clear()
        state.update(FIXTURE["states"]["maintenance"])
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert state_of("switch", "blackout") == "off"
        assert state_of("sensor", "operating_mode") == "maintenance"
        state.clear()
        state.update(FIXTURE["states"]["normal"])
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert state_of("switch", "maintenance") == "off"
        assert state_of("sensor", "maintenance_ends_at") == "unknown"
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_countdown_timestamp_is_published_with_its_state(
    device: SunRiserCoordinator,
) -> None:
    now = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
    device.data = {**FIXTURE["states"]["blackout"], "_state_received_at": now}
    old_end = device.maintenance_ends_at
    device.async_get_state = AsyncMock(
        return_value={**FIXTURE["states"]["blackout"], "service_left": 870}
    )
    with patch(
        "custom_components.sunriser.coordinator.dt_util.utcnow",
        return_value=now + timedelta(seconds=30),
    ):
        next_snapshot = await device._async_refresh_state()
    # Config listeners may run before the full poll publishes its new snapshot.
    assert device.maintenance_ends_at == old_end
    device.data = next_snapshot
    assert device.maintenance_ends_at == old_end
