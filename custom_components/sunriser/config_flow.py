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
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback

from .const import CONF_SCAN_INTERVAL, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


async def _test_connection(host: str, port: int, password: str) -> str | None:
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
            password = user_input.get(CONF_PASSWORD, "")

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            error = await _test_connection(host, port, password)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=host,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_PASSWORD: password or None,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a device discovered via DHCP."""
        await self.async_set_unique_id(discovery_info.macaddress)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})

        # Test the connection before bothering the user.
        error = await _test_connection(discovery_info.ip, DEFAULT_PORT, "")
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
                    CONF_PASSWORD: None,
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
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_interval = self._entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        int, vol.Range(min=5, max=3600)
                    ),
                }
            ),
        )
