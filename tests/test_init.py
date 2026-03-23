# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for custom_components/sunriser/__init__.py (setup and unload)."""

import aiohttp
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError

from tests.conftest import ENTRY_ID, FAKE_STATE
from custom_components.sunriser import (
    _async_reload_entry,
    _get_coordinator,
    _register_services,
)
from custom_components.sunriser.const import DOMAIN


async def test_setup_entry_success(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator._async_update_data",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert ENTRY_ID in hass.data[DOMAIN]


async def test_setup_entry_client_error_raises_not_ready(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
        side_effect=aiohttp.ClientError("down"),
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # HA marks the entry as not ready when ConfigEntryNotReady is raised
    assert result is False
    assert mock_config_entry.state.value in ("setup_error", "setup_retry")


async def test_setup_entry_unexpected_error_raises_not_ready(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
        side_effect=RuntimeError("unexpected"),
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is False


async def test_unload_entry_closes_open_session(hass, mock_config_entry):
    """When the coordinator has an open aiohttp session it is closed on unload."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator._async_update_data",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Inject an open mock session into the coordinator so the close branch is hit
        coordinator = hass.data[DOMAIN][ENTRY_ID]
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.close = AsyncMock()
        coordinator._session = mock_session

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    mock_session.close.assert_awaited_once()


async def test_reload_entry_on_options_change(hass, mock_config_entry):
    """_async_reload_entry triggers an entry reload."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator._async_update_data",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        with patch.object(
            hass.config_entries, "async_reload", new=AsyncMock()
        ) as mock_reload:
            await _async_reload_entry(hass, mock_config_entry)

    mock_reload.assert_awaited_once_with(ENTRY_ID)


async def test_unload_entry(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator._async_update_data",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert ENTRY_ID not in hass.data.get(DOMAIN, {})


# ---------------------------------------------------------------------------
# Helpers for service tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def setup_entry(hass, mock_config_entry):
    """Set up the integration entry and return the coordinator."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.sunriser.coordinator.SunRiserCoordinator._async_update_data",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return hass.data[DOMAIN][ENTRY_ID]


# ---------------------------------------------------------------------------
# _get_coordinator / _register_services
# ---------------------------------------------------------------------------


async def test_get_coordinator_raises_when_not_loaded(hass):
    with pytest.raises(HomeAssistantError, match="not loaded"):
        _get_coordinator(hass)


async def test_register_services_is_reentrant(hass, setup_entry):
    """Calling _register_services a second time must be a no-op."""
    _register_services(hass)
    assert hass.services.has_service(DOMAIN, "backup")


# ---------------------------------------------------------------------------
# Service handlers
# ---------------------------------------------------------------------------


async def test_service_backup(hass, setup_entry):
    coordinator = setup_entry
    coordinator.async_get_backup = AsyncMock(return_value=b"\x80")

    from unittest.mock import mock_open as _mock_open

    m = _mock_open()
    with patch("builtins.open", m):
        result = await hass.services.async_call(
            DOMAIN, "backup", {}, blocking=True, return_response=True
        )

    coordinator.async_get_backup.assert_awaited_once()
    m().write.assert_called_once_with(b"\x80")
    assert "path" in result
    assert result["path"].endswith(".msgpack")


async def test_service_restore(hass, setup_entry):
    coordinator = setup_entry
    coordinator.async_restore = AsyncMock()

    from unittest.mock import mock_open as _mock_open

    m = _mock_open(read_data=b"\x80")
    with (
        patch.object(hass.config, "is_allowed_path", return_value=True),
        patch("builtins.open", m),
    ):
        await hass.services.async_call(
            DOMAIN, "restore", {"file_path": "/config/backup.msgpack"}, blocking=True
        )

    coordinator.async_restore.assert_awaited_once_with(b"\x80")


async def test_service_restore_disallowed_path(hass, setup_entry):
    with patch.object(hass.config, "is_allowed_path", return_value=False):
        with pytest.raises(HomeAssistantError, match="not allowed"):
            await hass.services.async_call(
                DOMAIN, "restore", {"file_path": "/etc/passwd"}, blocking=True
            )


async def test_service_get_errors(hass, setup_entry):
    coordinator = setup_entry
    coordinator.async_get_errors = AsyncMock(return_value="error log content")

    result = await hass.services.async_call(
        DOMAIN, "get_errors", {}, blocking=True, return_response=True
    )

    assert result == {"content": "error log content"}


async def test_service_get_log(hass, setup_entry):
    coordinator = setup_entry
    coordinator.async_get_log = AsyncMock(return_value="diagnostic log content")

    result = await hass.services.async_call(
        DOMAIN, "get_log", {}, blocking=True, return_response=True
    )

    assert result == {"content": "diagnostic log content"}


# ---------------------------------------------------------------------------
# async_setup — static path + add_extra_js_url
# ---------------------------------------------------------------------------


async def test_async_setup_registers_static_path_and_js_url(hass, mock_http_frontend):
    """async_setup must register the card JS as a static path and add it as an extra JS URL."""
    from custom_components.sunriser import async_setup
    from unittest.mock import patch as _patch, call as _call

    with _patch("custom_components.sunriser.add_extra_js_url") as mock_add_js:
        result = await async_setup(hass, {})

    assert result is True
    mock_http_frontend.async_register_static_paths.assert_awaited_once()
    # The registered URL must be the card URL
    args = mock_http_frontend.async_register_static_paths.call_args[0][0]
    assert args[0].url_path == "/sunriser/sunriser-dayplan-card.js"
    mock_add_js.assert_called_once_with(hass, "/sunriser/sunriser-dayplan-card.js")


# ---------------------------------------------------------------------------
# Dayplanner service handlers
# ---------------------------------------------------------------------------


async def test_service_get_dayplanner_schedule(hass, setup_entry):
    coordinator = setup_entry
    coordinator.config["pwm#1#color"] = "4500k"
    coordinator.async_get_dayplanner = AsyncMock(
        return_value=[{"time": "08:00", "percent": 50}]
    )

    result = await hass.services.async_call(
        DOMAIN,
        "get_dayplanner_schedule",
        {"pwm": 1},
        blocking=True,
        return_response=True,
    )

    coordinator.async_get_dayplanner.assert_awaited_once_with(1)
    assert result["pwm"] == 1
    assert result["color_id"] == "4500k"
    assert result["markers"] == [{"time": "08:00", "percent": 50}]
    assert "name" in result


async def test_service_set_dayplanner_schedule(hass, setup_entry):
    coordinator = setup_entry
    coordinator.async_set_dayplanner = AsyncMock()

    markers = [{"time": "08:00", "percent": 50}, {"time": "20:00", "percent": 0}]
    await hass.services.async_call(
        DOMAIN,
        "set_dayplanner_schedule",
        {"pwm": 2, "markers": markers},
        blocking=True,
    )

    coordinator.async_set_dayplanner.assert_awaited_once_with(2, markers)
