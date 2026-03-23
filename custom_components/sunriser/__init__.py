# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import pathlib

import aiohttp
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PLATFORMS
from .coordinator import SunRiserCoordinator

_CARD_URL = "/sunriser/sunriser-dayplan-card.js"
_CARD_PATH = pathlib.Path(__file__).parent / "www" / "sunriser-dayplan-card.js"

_LOGGER = logging.getLogger(__name__)

_SERVICE_BACKUP = "backup"
_SERVICE_RESTORE = "restore"
_SERVICE_GET_ERRORS = "get_errors"
_SERVICE_GET_LOG = "get_log"
_SERVICE_GET_DAYPLANNER = "get_dayplanner_schedule"
_SERVICE_SET_DAYPLANNER = "set_dayplanner_schedule"
_ALL_SERVICES = (
    _SERVICE_BACKUP,
    _SERVICE_RESTORE,
    _SERVICE_GET_ERRORS,
    _SERVICE_GET_LOG,
    _SERVICE_GET_DAYPLANNER,
    _SERVICE_SET_DAYPLANNER,
)

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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the Day Planner card as a frontend resource."""
    hass.http.register_static_path(_CARD_URL, str(_CARD_PATH), cache_headers=False)
    add_extra_js_url(hass, _CARD_URL)
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _register_services(hass)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: SunRiserCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
        for svc in _ALL_SERVICES:
            hass.services.async_remove(DOMAIN, svc)
    return unload_ok


def _get_coordinator(hass: HomeAssistant) -> SunRiserCoordinator:
    entries = hass.data.get(DOMAIN, {})
    try:
        return next(iter(entries.values()))
    except StopIteration:
        raise HomeAssistantError("SunRiser integration not loaded") from None


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, _SERVICE_BACKUP):
        return  # already registered (re-entrant safety)

    async def handle_backup(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        data = await coordinator.async_get_backup()
        now = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sunriser_backup_{now}.msgpack"
        path = hass.config.path(filename)

        def _write() -> None:
            with open(path, "wb") as f:
                f.write(data)

        await hass.async_add_executor_job(_write)
        _LOGGER.info("SunRiser backup saved to %s", path)
        return {"path": path}

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

        data = await hass.async_add_executor_job(_read)
        coordinator = _get_coordinator(hass)
        await coordinator.async_restore(data)

    async def handle_get_errors(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        content = await coordinator.async_get_errors()
        return {"content": content}

    async def handle_get_log(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        content = await coordinator.async_get_log()
        return {"content": content}

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

    async def handle_get_dayplanner(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        pwm: int = call.data["pwm"]
        markers = await coordinator.async_get_dayplanner(pwm)
        return {
            "pwm": pwm,
            "name": coordinator.pwm_name(pwm),
            "color_id": coordinator.config.get(f"pwm#{pwm}#color") or "",
            "markers": markers,
        }

    async def handle_set_dayplanner(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.async_set_dayplanner(call.data["pwm"], call.data["markers"])

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
