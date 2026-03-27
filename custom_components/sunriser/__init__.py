# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import pathlib
from typing import Any, TypedDict, cast

import aiohttp
import msgpack
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import (
    CoreState,
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PLATFORMS

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

from .coordinator import DayplannerMarker, SunRiserCoordinator

_CARD_URL = "/sunriser/sunriser-dayplan-card.js"
_CARD_PATH = pathlib.Path(__file__).parent / "www" / "sunriser-dayplan-card.js"
_CARD_VERSION = "1.4.8"

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

_RESTORE_SCHEMA = vol.Schema({vol.Required("file_path"): cv.string})

_GET_DAYPLANNER_SCHEMA = vol.Schema(
    {vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10))}
)

_MARKER_SCHEMA = vol.Schema(
    {
        vol.Required("time"): vol.All(
            cv.string,
            vol.Match(r"^\d{1,2}:\d{2}$"),
        ),
        vol.Required("percent"): vol.All(int, vol.Range(min=0, max=100)),
    }
)
_SET_DAYPLANNER_SCHEMA = vol.Schema(
    {
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
    {vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10))}
)

_SET_WEEKPLANNER_SCHEMA = vol.Schema(
    {
        vol.Required("pwm"): vol.All(int, vol.Range(min=1, max=10)),
        vol.Required("schedule"): vol.Schema(
            {vol.In(_WEEK_DAYS): vol.All(int, vol.Range(min=0))}
        ),
    }
)

_FACTORY_RESET_SCHEMA = vol.Schema(
    {vol.Required("confirm"): vol.All(bool, vol.IsTrue())}
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Serve the Day Planner card JS and register it as a Lovelace resource."""
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
                    await resources.async_update_item(
                        item["id"], {"res_type": "module", "url": url_versioned}
                    )
                return

        if isinstance(resources, ResourceStorageCollection):
            await resources.async_create_item(
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

    try:
        await coordinator.async_load_device_config()
    except aiohttp.ClientError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to SunRiser at {coordinator.host}: {err}"
        ) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error loading SunRiser device config")
        raise ConfigEntryNotReady(f"Unexpected error: {err}") from err

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Platform setup is deferred until all four init ticks complete so that
    # coordinator.config has PWM names, colors, and weather data before any
    # entity is created.  Each init tick makes exactly one HTTP request so the
    # WizFi360 has a full poll interval between connections.
    _platforms_loaded = False

    @callback
    def _on_coordinator_update() -> None:
        nonlocal _platforms_loaded
        if _platforms_loaded or not coordinator.init_complete:
            return
        _platforms_loaded = True
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        )

    entry.async_on_unload(coordinator.async_add_listener(_on_coordinator_update))

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: SunRiserCoordinator = entry.runtime_data
        await coordinator.async_close()
    return unload_ok


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


def _get_coordinator(hass: HomeAssistant) -> SunRiserCoordinator:
    entries = hass.config_entries.async_entries(DOMAIN)
    try:
        return cast(SunRiserCoordinator, next(iter(entries)).runtime_data)
    except StopIteration:
        raise HomeAssistantError("SunRiser integration not loaded") from None


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, _SERVICE_BACKUP):
        return  # already registered (re-entrant safety)

    async def handle_backup(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        try:
            data = await coordinator.async_get_backup()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to retrieve backup from SunRiser: {err}"
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_backup_{now}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "wb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                f"Failed to write backup file {path}: {err}"
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
            raise HomeAssistantError(f"Path not allowed by Home Assistant: {file_path}")

        def _read() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        try:
            data = await hass.async_add_executor_job(_read)
        except OSError as err:
            raise HomeAssistantError(
                f"Failed to read backup file {file_path}: {err}"
            ) from err
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.async_restore(data)
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to restore backup to SunRiser: {err}"
            ) from err

    async def handle_get_errors(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        try:
            content = await coordinator.async_get_errors()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to retrieve error log from SunRiser: {err}"
            ) from err
        result: _ContentResponse = {"content": content}
        return cast(ServiceResponse, result)

    async def handle_get_log(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        try:
            content = await coordinator.async_get_log()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to retrieve log from SunRiser: {err}"
            ) from err
        result: _ContentResponse = {"content": content}
        return cast(ServiceResponse, result)

    hass.services.async_register(
        DOMAIN,
        _SERVICE_BACKUP,
        handle_backup,
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
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_GET_LOG,
        handle_get_log,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def handle_get_dayplanner(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
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
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.async_set_dayplanner(
                call.data["pwm"], call.data["markers"]
            )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to update day planner for PWM {call.data['pwm']}: {err}"
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
        coordinator = _get_coordinator(hass)
        pwm: int = call.data["pwm"]
        try:
            schedule = await coordinator.async_get_weekplanner(pwm)
        except (aiohttp.ClientError, msgpack.UnpackException) as err:
            raise HomeAssistantError(
                f"Failed to retrieve week planner for PWM {pwm}: {err}"
            ) from err
        result: _WeekplannerScheduleResponse = {
            "pwm": pwm,
            "name": coordinator.pwm_name(pwm),
            "color_id": coordinator.config.get(f"pwm#{pwm}#color") or "",
            "schedule": schedule,
        }
        return cast(ServiceResponse, result)

    async def handle_set_weekplanner(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.async_set_weekplanner(
                call.data["pwm"], call.data["schedule"]
            )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to update week planner for PWM {call.data['pwm']}: {err}"
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

    async def handle_factory_backup(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        try:
            data = await coordinator.async_get_factory_backup()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to retrieve factory backup from SunRiser: {err}"
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_factory_backup_{now}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "wb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                f"Failed to write factory backup file {path}: {err}"
            ) from err
        _LOGGER.info("SunRiser factory backup saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_firmware(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        try:
            data = await coordinator.async_get_firmware()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to retrieve firmware info from SunRiser: {err}"
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_firmware_{now}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "wb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                f"Failed to write firmware file {path}: {err}"
            ) from err
        _LOGGER.info("SunRiser firmware info saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_bootload(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        try:
            data = await coordinator.async_get_bootload()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to retrieve bootload info from SunRiser: {err}"
            ) from err
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_bootload_{now}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "wb") as f:
                f.write(data)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            raise HomeAssistantError(
                f"Failed to write bootload file {path}: {err}"
            ) from err
        _LOGGER.info("SunRiser bootload info saved to %s", path)
        result: _FilePathResponse = {"path": path}
        return cast(ServiceResponse, result)

    async def handle_factory_reset(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.async_factory_reset()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Failed to send factory reset to SunRiser: {err}"
            ) from err
        _LOGGER.warning("SunRiser factory reset triggered — all config wiped")

    hass.services.async_register(
        DOMAIN,
        _SERVICE_FACTORY_BACKUP,
        handle_factory_backup,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_FIRMWARE,
        handle_firmware,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_BOOTLOAD,
        handle_bootload,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_FACTORY_RESET,
        handle_factory_reset,
        schema=_FACTORY_RESET_SCHEMA,
    )
