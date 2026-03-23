# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for custom_components/sunriser/__init__.py (setup and unload)."""

import aiohttp
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import ENTRY_ID, FAKE_STATE
from custom_components.sunriser import _async_reload_entry
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
