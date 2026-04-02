# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_REBOOT_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULED_REBOOT,
    DEFAULT_PORT,
    DEFAULT_REBOOT_TIME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


async def _test_connection(host: str, port: int) -> str | None:
    """Return None on success or an error key string on failure."""
    url = f"http://{host}:{port}/ok"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return "cannot_connect"
                text = await resp.text()
                if text.strip() != "OK":
                    return "cannot_connect"
    except aiohttp.ClientConnectorError:
        return "cannot_connect"
    except TimeoutError:
        return "timeout"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error connecting to %s", host)
        return "unknown"
    return None


class SunRiserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI config flow for SunRiser."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SunRiserOptionsFlow:
        return SunRiserOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            error = await _test_connection(host, port)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=host,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            error = await _test_connection(host, port)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str,
                    vol.Optional(
                        CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ): int,
                }
            ),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a device discovered via DHCP."""
        await self.async_set_unique_id(discovery_info.macaddress)

        # If an entry already exists for this MAC, update the host and reload.
        for entry in self._async_current_entries():
            if entry.unique_id == discovery_info.macaddress:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_HOST: discovery_info.ip},
                    reason="already_configured",
                )

        # New device — test connectivity then confirm with user.
        error = await _test_connection(discovery_info.ip, DEFAULT_PORT)
        if error:
            return self.async_abort(reason=error)

        self._discovered_host = discovery_info.ip
        return await self.async_step_dhcp_confirm()

    async def async_step_dhcp_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a DHCP-discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_host,
                data={
                    CONF_HOST: self._discovered_host,
                    CONF_PORT: DEFAULT_PORT,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="dhcp_confirm",
            description_placeholders={"host": self._discovered_host},
        )


class SunRiserOptionsFlow(OptionsFlow):
    """Handle options for an existing SunRiser entry."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            reboot_time = user_input.get(CONF_REBOOT_TIME, DEFAULT_REBOOT_TIME)
            try:
                hour, minute = (int(p) for p in reboot_time.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                errors[CONF_REBOOT_TIME] = "invalid_time"
            if not errors:
                return self.async_create_entry(data=user_input)

        current_interval = self._entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_reboot_enabled = self._entry.options.get(CONF_SCHEDULED_REBOOT, True)
        current_reboot_time = self._entry.options.get(
            CONF_REBOOT_TIME, DEFAULT_REBOOT_TIME
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        int, vol.Range(min=5, max=3600)
                    ),
                    vol.Optional(
                        CONF_SCHEDULED_REBOOT, default=current_reboot_enabled
                    ): bool,
                    vol.Optional(CONF_REBOOT_TIME, default=current_reboot_time): str,
                }
            ),
            errors=errors,
        )
