"""Service calls select a loaded controller and never silently pick another."""

from unittest.mock import AsyncMock, mock_open, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser import _get_coordinator, _register_services
from custom_components.sunriser.const import DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator


@pytest.fixture
async def controllers(hass):
    result = []
    for i in range(2):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"controller_{i}",
            data={"host": f"192.0.2.{i + 1}"},
            options={"scheduled_reboot": False},
        )
        entry.add_to_hass(hass)
        coord = SunRiserCoordinator(hass, entry)
        entry.runtime_data = coord
        entry._async_set_state(hass, ConfigEntryState.LOADED, None)
        device = device_registry.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
        )
        result.append((entry, coord, device))
    _register_services(hass)
    yield result
    for _, coord, _ in result:
        await coord.async_close()


async def test_ambiguous_service_requires_selection(hass, controllers):
    for _, coord, _ in controllers:
        coord.async_factory_reset = AsyncMock()
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "factory_reset", {"confirm": True}, blocking=True
        )
    assert error.value.translation_key == "device_required"
    for _, coord, _ in controllers:
        coord.async_factory_reset.assert_not_awaited()


async def test_unloaded_first_entry_is_skipped(hass, controllers):
    entry, _, _ = controllers[0]
    entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    del entry.runtime_data
    assert _get_coordinator(hass) is controllers[1][1]


@pytest.mark.parametrize("selection", ["unknown", "unloaded", "foreign"])
async def test_invalid_selected_device_does_not_fall_back(hass, controllers, selection):
    entry, _, device = controllers[0]
    selected_id = device.id
    if selection == "unknown":
        selected_id = "does-not-exist"
    elif selection == "unloaded":
        entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    else:
        foreign = MockConfigEntry(domain="other", unique_id="foreign")
        foreign.add_to_hass(hass)
        device = device_registry.async_get(hass).async_get_or_create(
            config_entry_id=foreign.entry_id,
            identifiers={("other", "foreign")},
        )
        selected_id = device.id
    with pytest.raises(HomeAssistantError) as error:
        _get_coordinator(hass, selected_id)
    assert error.value.translation_key == "integration_not_loaded"


@pytest.mark.parametrize(
    "service,method,data,result,response",
    [
        ("backup", "async_get_backup", {}, b"backup", True),
        (
            "restore",
            "async_restore",
            {"file_path": "/config/backup.msgpack"},
            None,
            False,
        ),
        ("get_errors", "async_get_errors", {}, "errors", True),
        ("get_log", "async_get_log", {}, "log", True),
        ("get_dayplanner_schedule", "async_get_dayplanner", {"pwm": 1}, [], True),
        (
            "set_dayplanner_schedule",
            "async_set_dayplanner",
            {"pwm": 1, "markers": [{"time": "08:00", "percent": 50}]},
            None,
            False,
        ),
        ("get_weekplanner_schedule", "async_get_weekplanner", {"pwm": 1}, {}, True),
        (
            "set_weekplanner_schedule",
            "async_set_weekplanner",
            {"pwm": 1, "schedule": {"monday": 2}},
            None,
            False,
        ),
        ("download_factory_backup", "async_get_factory_backup", {}, b"factory", True),
        ("download_firmware", "async_get_firmware", {}, b"firmware", True),
        ("download_bootload", "async_get_bootload", {}, b"bootload", True),
        ("factory_reset", "async_factory_reset", {"confirm": True}, None, False),
    ],
)
async def test_each_service_targets_selected_controller(
    hass,
    controllers,
    service,
    method,
    data,
    result,
    response,
):
    first, second = controllers[0][1], controllers[1][1]
    setattr(first, method, AsyncMock(return_value=result))
    setattr(second, method, AsyncMock(return_value=result))
    with (
        patch("builtins.open", mock_open(read_data=b"backup")),
        patch.object(hass.config, "is_allowed_path", return_value=True),
    ):
        await hass.services.async_call(
            DOMAIN,
            service,
            {**data, "device_id": controllers[1][2].id},
            blocking=True,
            return_response=response,
        )
    getattr(first, method).assert_not_awaited()
    getattr(second, method).assert_awaited_once()
