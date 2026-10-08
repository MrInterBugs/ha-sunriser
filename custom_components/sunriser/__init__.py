# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
from __future__ import annotations

import logging
import pathlib
from typing import Any, TypedDict, cast
from uuid import uuid4

import aiohttp
import msgpack
import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import (
    CoreState,
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry
from homeassistant.helpers.issue_registry import async_delete_issue
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PLATFORMS
from .coordinator import DayplannerMarker, SunRiserCoordinator
from .responses import InvalidResponse

CONFIG_SCHEMA = cv.config_entry_only_config_schema(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    DOMAIN
)


_CARD_URL = "/sunriser/sunriser-dayplan-card.js"
_CARD_PATH = pathlib.Path(__file__).parent / "www" / "sunriser-dayplan-card.js"
_CARD_VERSION = "1.5.1"

_LOGGER = logging.getLogger(__name__)

_SERVICE_BACKUP = "backup"
_SERVICE_RESTORE = "restore"
_SERVICE_GET_ERRORS = "get_errors"
_SERVICE_GET_LOG = "get_log"
_SERVICE_GET_DAYPLANNER = "get_dayplanner_schedule"
_SERVICE_SET_DAYPLANNER = "set_dayplanner_schedule"
_SERVICE_GET_WEEKPLANNER = "get_weekplanner_schedule"
_SERVICE_SET_WEEKPLANNER = "set_weekplanner_schedule"
_SERVICE_FACTORY_BACKUP = "download_factory_backup"
_SERVICE_FIRMWARE = "download_firmware"
_SERVICE_BOOTLOAD = "download_bootload"
_SERVICE_FACTORY_RESET = "factory_reset"

_DEVICE_FIELDS: dict[vol.Marker, Any] = {vol.Optional("device_id"): cv.string}
_DEVICE_SCHEMA = vol.Schema(_DEVICE_FIELDS)
_RESTORE_SCHEMA = vol.Schema({**_DEVICE_FIELDS, vol.Required("file_path"): cv.string})

_GET_DAYPLANNER_SCHEMA = vol.Schema(
    {**_DEVICE_FIELDS, vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10))}
)

_MARKER_SCHEMA = vol.Schema(
    {
        vol.Required("time"): vol.All(
            cv.string,
            vol.Match(r"^(?:(?:[01]?[0-9]|2[0-3]):[0-5][0-9]|24:00)\Z"),
        ),
        vol.Required("percent"): vol.All(int, vol.Range(min=0, max=100)),
    }
)
_SET_DAYPLANNER_SCHEMA = vol.Schema(
    {
        **_DEVICE_FIELDS,
        vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10)),
        vol.Required("markers"): vol.All(
            [_MARKER_SCHEMA],
            vol.Length(min=1),
        ),
    }
)

_WEEK_DAYS = [
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "default",
]

_GET_WEEKPLANNER_SCHEMA = vol.Schema(
    {**_DEVICE_FIELDS, vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10))}
)

_SET_WEEKPLANNER_SCHEMA = vol.Schema(
    {
        **_DEVICE_FIELDS,
        vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10)),
        vol.Required("schedule"): vol.Schema(
            {vol.In(_WEEK_DAYS): vol.All(int, vol.Range(min=0))}
        ),
    }
)

_FACTORY_RESET_SCHEMA = vol.Schema(
    {
        **_DEVICE_FIELDS,
        vol.Required("confirm"): vol.All(
            bool,
            vol.IsTrue(),  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Serve the Day Planner card JS and register it as a Lovelace resource."""
    # Older releases shared one repair across controllers. Each coordinator
    # now owns its repair and will recreate it if that controller is offline.
    async_delete_issue(hass, DOMAIN, "device_unreachable")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_CARD_URL, str(_CARD_PATH), cache_headers=False)]
    )

    async def _register(_event: Event | None = None) -> None:
        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.warning(
                "SunRiser: lovelace not available, falling back to add_extra_js_url"
            )
            add_extra_js_url(hass, f"{_CARD_URL}?v={_CARD_VERSION}")
            return

        resources = lovelace.resources
        await resources.async_get_info()

        url_versioned = f"{_CARD_URL}?v={_CARD_VERSION}"
        for item in resources.async_items():
            item_url: str = item.get("url", "")
            if item_url.split("?")[0] == _CARD_URL:
                if item_url != url_versioned and isinstance(
                    resources, ResourceStorageCollection
                ):
                    await resources.async_update_item(  # pyright: ignore[reportUnknownMemberType]  # Upstream HA/Voluptuous annotations.
                        item["id"], {"res_type": "module", "url": url_versioned}
                    )
                return

        if isinstance(resources, ResourceStorageCollection):
            await resources.async_create_item(  # pyright: ignore[reportUnknownMemberType]  # Upstream HA/Voluptuous annotations.
                {"res_type": "module", "url": url_versioned}
            )
            _LOGGER.debug("SunRiser: registered Day Planner card as Lovelace resource")
        else:
            add_extra_js_url(hass, url_versioned)

    if hass.state == CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)

    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = SunRiserCoordinator(hass, entry)

    ready = False
    try:
        try:
            await coordinator.async_load_device_config()
        except (aiohttp.ClientError, TimeoutError, InvalidResponse) as err:
            raise ConfigEntryNotReady(
                f"Cannot read SunRiser configuration at {coordinator.host}: {err}"
            ) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error loading SunRiser device config")
            raise ConfigEntryNotReady(f"Unexpected error: {err}") from err

        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        ready = True
    finally:
        if not ready:
            await coordinator.async_close()

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: SunRiserCoordinator = entry.runtime_data
    # Save in-memory state that must survive a same-session reload (options change,
    # reconfigure).  RestoreEntity covers HA restarts via the recorder.
    hass.data.setdefault(DOMAIN, {})[
        f"{entry.entry_id}_dst_auto_track"
    ] = coordinator.dst_auto_track
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_close()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove persistent repairs and restored helper state for a deleted controller."""
    async_delete_issue(hass, DOMAIN, f"device_unreachable_{entry.entry_id}")
    hass.data.get(DOMAIN, {}).pop(f"{entry.entry_id}_dst_auto_track", None)


class _FilePathResponse(TypedDict):
    path: str


class _ContentResponse(TypedDict):
    content: str


class _DayplannerScheduleResponse(TypedDict):
    pwm: int
    name: str
    color_id: str
    markers: list[DayplannerMarker]


class _WeekplannerScheduleResponse(TypedDict):
    pwm: int
    name: str
    color_id: str
    schedule: dict[str, int | None]


def _get_coordinator(
    hass: HomeAssistant, device_id: str | None = None
) -> SunRiserCoordinator:
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and isinstance(getattr(entry, "runtime_data", None), SunRiserCoordinator)
    ]
    if device_id is not None:
        device = device_registry.async_get(hass).async_get(device_id)
        entries = [
            entry
            for entry in entries
            if device is not None and entry.entry_id in device.config_entries
        ]
    if not entries:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="integration_not_loaded",
        )
    if len(entries) != 1:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_required",
        )
    return cast(SunRiserCoordinator, entries[0].runtime_data)


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, _SERVICE_BACKUP):
        return  # already registered (re-entrant safety)

    async def handle_backup(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            data = await coordinator.async_get_backup()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="backup_retrieve_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_backup_{now}_{coordinator.entry_id}_{uuid4().hex}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "xb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="backup_write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        _LOGGER.info("SunRiser backup saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_restore(call: ServiceCall) -> None:
        from pathlib import Path

        file_path: str = call.data["file_path"]
        config_dir = Path(hass.config.config_dir).resolve()
        in_config_dir = Path(file_path).resolve().is_relative_to(config_dir)
        if not in_config_dir and not hass.config.is_allowed_path(file_path):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="path_not_allowed",
                translation_placeholders={"path": file_path},
            )

        def _read() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        try:
            data = await hass.async_add_executor_job(_read)
        except OSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="restore_read_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            await coordinator.async_restore(data)
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="restore_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def handle_get_errors(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            content = await coordinator.async_get_errors()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="get_errors_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        result: _ContentResponse = {"content": content}
        return cast(ServiceResponse, result)

    async def handle_get_log(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            content = await coordinator.async_get_log()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="get_log_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        result: _ContentResponse = {"content": content}
        return cast(ServiceResponse, result)

    hass.services.async_register(
        DOMAIN,
        _SERVICE_BACKUP,
        handle_backup,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_RESTORE,
        handle_restore,
        schema=_RESTORE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_GET_ERRORS,
        handle_get_errors,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_GET_LOG,
        handle_get_log,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_get_dayplanner(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        pwm: int = call.data["pwm"]
        markers = await coordinator.async_get_dayplanner(pwm)
        result: _DayplannerScheduleResponse = {
            "pwm": pwm,
            "name": coordinator.pwm_name(pwm),
            "color_id": coordinator.config.get(f"pwm#{pwm}#color") or "",
            "markers": markers,
        }
        return cast(ServiceResponse, result)

    async def handle_set_dayplanner(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            await coordinator.async_set_dayplanner(
                call.data["pwm"], call.data["markers"]
            )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_dayplanner_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    hass.services.async_register(
        DOMAIN,
        _SERVICE_GET_DAYPLANNER,
        handle_get_dayplanner,
        schema=_GET_DAYPLANNER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_SET_DAYPLANNER,
        handle_set_dayplanner,
        schema=_SET_DAYPLANNER_SCHEMA,
    )

    async def handle_get_weekplanner(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        pwm: int = call.data["pwm"]
        try:
            schedule = await coordinator.async_get_weekplanner(pwm)
        except (aiohttp.ClientError, msgpack.UnpackException) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="get_weekplanner_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        result: _WeekplannerScheduleResponse = {
            "pwm": pwm,
            "name": coordinator.pwm_name(pwm),
            "color_id": coordinator.config.get(f"pwm#{pwm}#color") or "",
            "schedule": schedule,
        }
        return cast(ServiceResponse, result)

    async def handle_set_weekplanner(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            await coordinator.async_set_weekplanner(
                call.data["pwm"], call.data["schedule"]
            )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_weekplanner_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    hass.services.async_register(
        DOMAIN,
        _SERVICE_GET_WEEKPLANNER,
        handle_get_weekplanner,
        schema=_GET_WEEKPLANNER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_SET_WEEKPLANNER,
        handle_set_weekplanner,
        schema=_SET_WEEKPLANNER_SCHEMA,
    )

    async def handle_get_planning(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            return cast(ServiceResponse, await coordinator.async_get_planning())
        except (aiohttp.ClientError, TimeoutError, InvalidResponse) as err:
            raise HomeAssistantError("Could not read controller schedules") from err

    hass.services.async_register(
        DOMAIN,
        "get_planning",
        handle_get_planning,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_factory_backup(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            data = await coordinator.async_get_factory_backup()
        except aiohttp.ClientResponseError as err:
            if err.status == 500:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="factory_backup_not_available",
                ) from err
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="factory_backup_retrieve_failed",
                translation_placeholders={"error": f"HTTP {err.status}"},
            ) from err
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="factory_backup_retrieve_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_factory_backup_{now}_{coordinator.entry_id}_{uuid4().hex}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "xb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="factory_backup_write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        _LOGGER.info("SunRiser factory backup saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_firmware(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            data = await coordinator.async_get_firmware()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="firmware_retrieve_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"sunriser_firmware_{now}_{coordinator.entry_id}_{uuid4().hex}.msgpack"
        )
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "xb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="firmware_write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        _LOGGER.info("SunRiser firmware info saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_bootload(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            data = await coordinator.async_get_bootload()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bootload_retrieve_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"sunriser_bootload_{now}_{coordinator.entry_id}_{uuid4().hex}.msgpack"
        )
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "xb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bootload_write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        _LOGGER.info("SunRiser bootload info saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_factory_reset(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        try:
            await coordinator.async_factory_reset()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="factory_reset_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        _LOGGER.warning("SunRiser factory reset triggered — all config wiped")

    hass.services.async_register(
        DOMAIN,
        _SERVICE_FACTORY_BACKUP,
        handle_factory_backup,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_FIRMWARE,
        handle_firmware,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_BOOTLOAD,
        handle_bootload,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_FACTORY_RESET,
        handle_factory_reset,
        schema=_FACTORY_RESET_SCHEMA,
    )
