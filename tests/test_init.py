# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for custom_components/sunriser/__init__.py (setup and unload)."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser import (
    _async_reload_entry,
    _get_coordinator,
    _register_services,
)
from custom_components.sunriser.const import DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator
from tests.conftest import ENTRY_ID, FAKE_STATE
from tests.typing import as_async_mock, response_path


async def test_setup_entry_success(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
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
    assert isinstance(mock_config_entry.runtime_data, SunRiserCoordinator)


async def test_setup_entry_client_error_raises_not_ready(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
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


async def test_setup_entry_unexpected_error_raises_not_ready(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.sunriser.coordinator.SunRiserCoordinator.async_load_device_config",
        side_effect=RuntimeError("unexpected"),
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is False


async def test_unload_entry_closes_open_session(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
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
        coordinator = mock_config_entry.runtime_data
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.close = AsyncMock()
        coordinator._session = mock_session

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    mock_session.close.assert_awaited_once()


async def test_unload_entry_saves_dst_auto_track_true_to_hass_data(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """async_unload_entry saves _dst_auto_track=True to hass.data for same-session reload."""
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

    coordinator = mock_config_entry.runtime_data
    coordinator.dst_auto_track = True

    result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert result is True
    from custom_components.sunriser.const import DOMAIN

    assert hass.data[DOMAIN][f"{ENTRY_ID}_dst_auto_track"] is True


async def test_unload_entry_saves_dst_auto_track_false_to_hass_data(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """async_unload_entry saves _dst_auto_track=False to hass.data (default state)."""
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

    coordinator = mock_config_entry.runtime_data
    assert coordinator.dst_auto_track is False  # default

    result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert result is True
    from custom_components.sunriser.const import DOMAIN

    assert hass.data[DOMAIN][f"{ENTRY_ID}_dst_auto_track"] is False


async def test_reload_entry_on_options_change(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
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


async def test_unload_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
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


async def test_platforms_forwarded_during_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Platforms are ready when setup returns, without waiting for poll ticks."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch.object(SunRiserCoordinator, "async_load_device_config", new=AsyncMock()),
        patch.object(
            SunRiserCoordinator,
            "_async_update_data",
            new=AsyncMock(return_value=FAKE_STATE),
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        forward.assert_awaited_once()
        await mock_config_entry.runtime_data.async_refresh()
        forward.assert_awaited_once()


# ---------------------------------------------------------------------------
# Helpers for service tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> SunRiserCoordinator:
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
    return mock_config_entry.runtime_data


# ---------------------------------------------------------------------------
# _get_coordinator / _register_services
# ---------------------------------------------------------------------------


async def test_get_coordinator_raises_when_not_loaded(hass: HomeAssistant) -> None:
    with pytest.raises(HomeAssistantError) as exc_info:
        _get_coordinator(hass)
    assert exc_info.value.translation_key == "integration_not_loaded"


async def test_register_services_is_reentrant(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    """Calling _register_services a second time must be a no-op."""
    _register_services(hass)
    assert hass.services.has_service(DOMAIN, "backup")


# ---------------------------------------------------------------------------
# Service handlers
# ---------------------------------------------------------------------------


async def test_service_backup(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_backup = AsyncMock(return_value=b"\x80")

    from unittest.mock import mock_open as _mock_open

    m = _mock_open()
    with patch("builtins.open", m):
        result = await hass.services.async_call(
            DOMAIN, "backup", {}, blocking=True, return_response=True
        )
        assert result is not None

    as_async_mock(coordinator.async_get_backup).assert_awaited_once()
    m().write.assert_called_once_with(b"\x80")
    assert "path" in result
    assert response_path(result).endswith(".msgpack")


async def test_service_restore(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
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

    as_async_mock(coordinator.async_restore).assert_awaited_once_with(b"\x80")


async def test_service_restore_disallowed_path(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    with patch.object(hass.config, "is_allowed_path", return_value=False):
        with pytest.raises(HomeAssistantError, match="not allowed"):
            await hass.services.async_call(
                DOMAIN, "restore", {"file_path": "/etc/passwd"}, blocking=True
            )


async def test_service_get_errors(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_errors = AsyncMock(return_value="error log content")

    result = await hass.services.async_call(
        DOMAIN, "get_errors", {}, blocking=True, return_response=True
    )
    assert result is not None

    assert result == {"content": "error log content"}


async def test_service_get_log(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_log = AsyncMock(return_value="diagnostic log content")

    result = await hass.services.async_call(
        DOMAIN, "get_log", {}, blocking=True, return_response=True
    )
    assert result is not None

    assert result == {"content": "diagnostic log content"}


# ---------------------------------------------------------------------------
# async_setup — static path + Lovelace resource registration
# ---------------------------------------------------------------------------


async def test_async_setup_registers_static_path_and_js_url(
    hass: HomeAssistant, mock_http_frontend: MagicMock
) -> None:
    """async_setup registers the card JS as a static path.

    When lovelace is unavailable (test env), it falls back to add_extra_js_url
    with a versioned URL (?v=<version>).
    """
    from unittest.mock import patch as _patch

    from custom_components.sunriser import _CARD_VERSION, async_setup

    with _patch("custom_components.sunriser.add_extra_js_url") as mock_add_js:
        result = await async_setup(hass, {})

    assert result is True
    mock_http_frontend.async_register_static_paths.assert_awaited_once()
    args = mock_http_frontend.async_register_static_paths.call_args[0][0]
    assert args[0].url_path == "/sunriser/sunriser-dayplan-card.js"
    mock_add_js.assert_called_once_with(
        hass, f"/sunriser/sunriser-dayplan-card.js?v={_CARD_VERSION}"
    )


async def test_async_setup_lovelace_url_already_current(hass: HomeAssistant) -> None:
    """Resource URL already matches the current version — no update is made."""
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    from custom_components.sunriser import _CARD_URL, _CARD_VERSION, async_setup

    url_versioned = f"{_CARD_URL}?v={_CARD_VERSION}"
    mock_resources = MagicMock(spec=ResourceStorageCollection)
    mock_resources.async_get_info = AsyncMock()
    mock_resources.async_items = MagicMock(
        return_value=[{"url": url_versioned, "id": "1"}]
    )
    mock_resources.async_update_item = AsyncMock()
    hass.data["lovelace"] = MagicMock(resources=mock_resources)

    result = await async_setup(hass, {})

    assert result is True
    mock_resources.async_update_item.assert_not_awaited()


async def test_async_setup_lovelace_url_stale_updates_resource(
    hass: HomeAssistant,
) -> None:
    """Resource URL is outdated — async_update_item is called with the new URL."""
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    from custom_components.sunriser import _CARD_URL, _CARD_VERSION, async_setup

    url_old = f"{_CARD_URL}?v=1.0.0"
    url_versioned = f"{_CARD_URL}?v={_CARD_VERSION}"
    mock_resources = MagicMock(spec=ResourceStorageCollection)
    mock_resources.async_get_info = AsyncMock()
    mock_resources.async_items = MagicMock(return_value=[{"url": url_old, "id": "abc"}])
    mock_resources.async_update_item = AsyncMock()
    hass.data["lovelace"] = MagicMock(resources=mock_resources)

    result = await async_setup(hass, {})

    assert result is True
    mock_resources.async_update_item.assert_awaited_once_with(
        "abc", {"res_type": "module", "url": url_versioned}
    )


async def test_async_setup_lovelace_no_resource_creates_item(
    hass: HomeAssistant,
) -> None:
    """No existing resource and storage-backed Lovelace — async_create_item is called."""
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    from custom_components.sunriser import _CARD_URL, _CARD_VERSION, async_setup

    url_versioned = f"{_CARD_URL}?v={_CARD_VERSION}"
    mock_resources = MagicMock(spec=ResourceStorageCollection)
    mock_resources.async_get_info = AsyncMock()
    mock_resources.async_items = MagicMock(return_value=[])
    mock_resources.async_create_item = AsyncMock()
    hass.data["lovelace"] = MagicMock(resources=mock_resources)

    result = await async_setup(hass, {})

    assert result is True
    mock_resources.async_create_item.assert_awaited_once_with(
        {"res_type": "module", "url": url_versioned}
    )


async def test_async_setup_lovelace_no_resource_not_storage_falls_back(
    hass: HomeAssistant,
) -> None:
    """No existing resource and non-storage Lovelace — falls back to add_extra_js_url."""
    from custom_components.sunriser import _CARD_URL, _CARD_VERSION, async_setup

    url_versioned = f"{_CARD_URL}?v={_CARD_VERSION}"
    mock_resources = MagicMock()  # not a ResourceStorageCollection
    mock_resources.async_get_info = AsyncMock()
    mock_resources.async_items = MagicMock(return_value=[])
    hass.data["lovelace"] = MagicMock(resources=mock_resources)

    with patch("custom_components.sunriser.add_extra_js_url") as mock_add_js:
        result = await async_setup(hass, {})

    assert result is True
    mock_add_js.assert_called_once_with(hass, url_versioned)


async def test_async_setup_ha_not_running_registers_listener(
    hass: HomeAssistant,
) -> None:
    """When HA is still starting, async_listen_once defers card registration."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    from custom_components.sunriser import async_setup

    original_state = hass.state
    hass.set_state(CoreState.starting)
    try:
        with patch.object(type(hass.bus), "async_listen_once") as mock_listen:
            result = await async_setup(hass, {})
    finally:
        hass.set_state(original_state)

    assert result is True
    mock_listen.assert_called_once()
    assert mock_listen.call_args[0][0] == EVENT_HOMEASSISTANT_STARTED


# ---------------------------------------------------------------------------
# Dayplanner service handlers
# ---------------------------------------------------------------------------


async def test_service_get_dayplanner_schedule(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
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
    assert result is not None

    as_async_mock(coordinator.async_get_dayplanner).assert_awaited_once_with(1)
    assert result["pwm"] == 1
    assert result["color_id"] == "4500k"
    assert result["markers"] == [{"time": "08:00", "percent": 50}]
    assert "name" in result


async def test_service_set_dayplanner_schedule(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_set_dayplanner = AsyncMock()

    markers = [{"time": "08:00", "percent": 50}, {"time": "20:00", "percent": 0}]
    await hass.services.async_call(
        DOMAIN,
        "set_dayplanner_schedule",
        {"pwm": 2, "markers": markers},
        blocking=True,
    )

    as_async_mock(coordinator.async_set_dayplanner).assert_awaited_once_with(2, markers)


# ---------------------------------------------------------------------------
# Weekplanner service handlers
# ---------------------------------------------------------------------------


async def test_service_get_weekplanner_schedule(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.config["pwm#4#color"] = "6500k"
    schedule = {
        "sunday": 0,
        "monday": 1,
        "tuesday": 1,
        "wednesday": 1,
        "thursday": 1,
        "friday": 1,
        "saturday": 0,
        "default": 1,
    }
    coordinator.async_get_weekplanner = AsyncMock(return_value=schedule)

    result = await hass.services.async_call(
        DOMAIN,
        "get_weekplanner_schedule",
        {"pwm": 4},
        blocking=True,
        return_response=True,
    )
    assert result is not None

    as_async_mock(coordinator.async_get_weekplanner).assert_awaited_once_with(4)
    assert result["pwm"] == 4
    assert result["schedule"] == schedule
    assert result["color_id"] == "6500k"
    assert "name" in result


async def test_service_set_weekplanner_schedule(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_set_weekplanner = AsyncMock()

    schedule = {"monday": 1, "default": 1}
    await hass.services.async_call(
        DOMAIN,
        "set_weekplanner_schedule",
        {"pwm": 4, "schedule": schedule},
        blocking=True,
    )

    as_async_mock(coordinator.async_set_weekplanner).assert_awaited_once_with(
        4, schedule
    )


# ---------------------------------------------------------------------------
# Dev service handlers — factory backup, firmware, bootload, factory reset
# ---------------------------------------------------------------------------


async def test_service_download_factory_backup(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_factory_backup = AsyncMock(return_value=b"\x80")

    from unittest.mock import mock_open as _mock_open

    m = _mock_open()
    with patch("builtins.open", m):
        result = await hass.services.async_call(
            DOMAIN, "download_factory_backup", {}, blocking=True, return_response=True
        )
        assert result is not None

    as_async_mock(coordinator.async_get_factory_backup).assert_awaited_once()
    m().write.assert_called_once_with(b"\x80")
    assert "path" in result
    assert "factory_backup" in response_path(result)
    assert response_path(result).endswith(".msgpack")


async def test_service_download_firmware(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_firmware = AsyncMock(return_value=b"\x81")

    from unittest.mock import mock_open as _mock_open

    m = _mock_open()
    with patch("builtins.open", m):
        result = await hass.services.async_call(
            DOMAIN, "download_firmware", {}, blocking=True, return_response=True
        )
        assert result is not None

    as_async_mock(coordinator.async_get_firmware).assert_awaited_once()
    m().write.assert_called_once_with(b"\x81")
    assert "path" in result
    assert "firmware" in response_path(result)
    assert response_path(result).endswith(".msgpack")


async def test_service_download_bootload(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_bootload = AsyncMock(return_value=b"\x82")

    from unittest.mock import mock_open as _mock_open

    m = _mock_open()
    with patch("builtins.open", m):
        result = await hass.services.async_call(
            DOMAIN, "download_bootload", {}, blocking=True, return_response=True
        )
        assert result is not None

    as_async_mock(coordinator.async_get_bootload).assert_awaited_once()
    m().write.assert_called_once_with(b"\x82")
    assert "path" in result
    assert "bootload" in response_path(result)
    assert response_path(result).endswith(".msgpack")


async def test_service_factory_reset(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_factory_reset = AsyncMock()

    await hass.services.async_call(
        DOMAIN, "factory_reset", {"confirm": True}, blocking=True
    )

    as_async_mock(coordinator.async_factory_reset).assert_awaited_once()


async def test_service_factory_reset_requires_confirm(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    """factory_reset must be rejected if confirm is not True."""
    import voluptuous

    with pytest.raises((voluptuous.MultipleInvalid, Exception)):
        await hass.services.async_call(
            DOMAIN, "factory_reset", {"confirm": False}, blocking=True
        )


# ---------------------------------------------------------------------------
# Error path tests — all service handlers must raise HomeAssistantError
# ---------------------------------------------------------------------------


async def test_service_backup_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_backup = AsyncMock(side_effect=aiohttp.ClientError("down"))

    with pytest.raises(HomeAssistantError, match="Failed to retrieve backup"):
        await hass.services.async_call(DOMAIN, "backup", {}, blocking=True)


async def test_service_backup_write_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_backup = AsyncMock(return_value=b"\x80")

    with (
        patch("builtins.open", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError, match="Failed to write backup file"),
    ):
        await hass.services.async_call(DOMAIN, "backup", {}, blocking=True)


async def test_service_restore_read_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    with (
        patch.object(hass.config, "is_allowed_path", return_value=True),
        patch("builtins.open", side_effect=OSError("not found")),
        pytest.raises(HomeAssistantError, match="Failed to read backup file"),
    ):
        await hass.services.async_call(
            DOMAIN, "restore", {"file_path": "/config/backup.msgpack"}, blocking=True
        )


async def test_service_restore_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_restore = AsyncMock(side_effect=aiohttp.ClientError("down"))

    from unittest.mock import mock_open as _mock_open

    m = _mock_open(read_data=b"\x80")
    with (
        patch.object(hass.config, "is_allowed_path", return_value=True),
        patch("builtins.open", m),
        pytest.raises(HomeAssistantError, match="Failed to restore backup"),
    ):
        await hass.services.async_call(
            DOMAIN, "restore", {"file_path": "/config/backup.msgpack"}, blocking=True
        )


async def test_service_get_errors_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_errors = AsyncMock(side_effect=aiohttp.ClientError("down"))

    with pytest.raises(HomeAssistantError, match="Failed to retrieve error log"):
        await hass.services.async_call(
            DOMAIN, "get_errors", {}, blocking=True, return_response=True
        )


async def test_service_get_log_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_log = AsyncMock(side_effect=aiohttp.ClientError("down"))

    with pytest.raises(HomeAssistantError, match="Failed to retrieve log"):
        await hass.services.async_call(
            DOMAIN, "get_log", {}, blocking=True, return_response=True
        )


async def test_service_set_dayplanner_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_set_dayplanner = AsyncMock(
        side_effect=aiohttp.ClientError("down")
    )

    markers = [{"time": "08:00", "percent": 50}]
    with pytest.raises(HomeAssistantError, match="Failed to update day planner"):
        await hass.services.async_call(
            DOMAIN,
            "set_dayplanner_schedule",
            {"pwm": 1, "markers": markers},
            blocking=True,
        )


async def test_service_get_weekplanner_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_weekplanner = AsyncMock(
        side_effect=aiohttp.ClientError("down")
    )

    with pytest.raises(HomeAssistantError, match="Failed to retrieve week planner"):
        await hass.services.async_call(
            DOMAIN,
            "get_weekplanner_schedule",
            {"pwm": 1},
            blocking=True,
            return_response=True,
        )


async def test_service_get_weekplanner_msgpack_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    import msgpack

    coordinator = setup_entry
    coordinator.async_get_weekplanner = AsyncMock(
        side_effect=msgpack.UnpackException("bad data")
    )

    with pytest.raises(HomeAssistantError, match="Failed to retrieve week planner"):
        await hass.services.async_call(
            DOMAIN,
            "get_weekplanner_schedule",
            {"pwm": 1},
            blocking=True,
            return_response=True,
        )


async def test_service_set_weekplanner_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_set_weekplanner = AsyncMock(
        side_effect=aiohttp.ClientError("down")
    )

    with pytest.raises(HomeAssistantError, match="Failed to update week planner"):
        await hass.services.async_call(
            DOMAIN,
            "set_weekplanner_schedule",
            {"pwm": 1, "schedule": {"default": 0}},
            blocking=True,
        )


async def test_service_factory_backup_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_factory_backup = AsyncMock(
        side_effect=aiohttp.ClientError("down")
    )

    with pytest.raises(HomeAssistantError, match="Failed to retrieve factory backup"):
        await hass.services.async_call(
            DOMAIN, "download_factory_backup", {}, blocking=True, return_response=True
        )


async def test_service_factory_backup_not_available(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    err = aiohttp.ClientResponseError(MagicMock(), (), status=500)
    coordinator.async_get_factory_backup = AsyncMock(side_effect=err)

    with pytest.raises(HomeAssistantError, match="CFGBACK1"):
        await hass.services.async_call(
            DOMAIN, "download_factory_backup", {}, blocking=True, return_response=True
        )


async def test_service_factory_backup_other_http_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    err = aiohttp.ClientResponseError(MagicMock(), (), status=503)
    coordinator.async_get_factory_backup = AsyncMock(side_effect=err)

    with pytest.raises(HomeAssistantError, match="Failed to retrieve factory backup"):
        await hass.services.async_call(
            DOMAIN, "download_factory_backup", {}, blocking=True, return_response=True
        )


async def test_service_factory_backup_write_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_factory_backup = AsyncMock(return_value=b"\x80")

    with (
        patch("builtins.open", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError, match="Failed to write factory backup file"),
    ):
        await hass.services.async_call(
            DOMAIN, "download_factory_backup", {}, blocking=True, return_response=True
        )


async def test_service_firmware_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_firmware = AsyncMock(side_effect=aiohttp.ClientError("down"))

    with pytest.raises(HomeAssistantError, match="Failed to retrieve firmware info"):
        await hass.services.async_call(
            DOMAIN, "download_firmware", {}, blocking=True, return_response=True
        )


async def test_service_firmware_write_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_firmware = AsyncMock(return_value=b"\x81")

    with (
        patch("builtins.open", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError, match="Failed to write firmware file"),
    ):
        await hass.services.async_call(
            DOMAIN, "download_firmware", {}, blocking=True, return_response=True
        )


async def test_service_bootload_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_bootload = AsyncMock(side_effect=aiohttp.ClientError("down"))

    with pytest.raises(HomeAssistantError, match="Failed to retrieve bootload info"):
        await hass.services.async_call(
            DOMAIN, "download_bootload", {}, blocking=True, return_response=True
        )


async def test_service_bootload_write_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_get_bootload = AsyncMock(return_value=b"\x82")

    with (
        patch("builtins.open", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError, match="Failed to write bootload file"),
    ):
        await hass.services.async_call(
            DOMAIN, "download_bootload", {}, blocking=True, return_response=True
        )


async def test_service_factory_reset_device_error(
    hass: HomeAssistant, setup_entry: SunRiserCoordinator
) -> None:
    coordinator = setup_entry
    coordinator.async_factory_reset = AsyncMock(side_effect=aiohttp.ClientError("down"))

    with pytest.raises(HomeAssistantError, match="Failed to send factory reset"):
        await hass.services.async_call(
            DOMAIN, "factory_reset", {"confirm": True}, blocking=True
        )
