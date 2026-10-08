# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser config flow and options flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.config_flow import _test_connection
from custom_components.sunriser.const import (
    CONF_REBOOT_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULED_REBOOT,
    DEFAULT_PORT,
    DOMAIN,
)
from tests.typing import require_value

HOST = "192.168.0.99"


async def _start_flow(hass: HomeAssistant) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


# ---------------------------------------------------------------------------
# _test_connection helper
# ---------------------------------------------------------------------------


async def test_test_connection_success() -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="OK")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_connection(HOST, DEFAULT_PORT)
    assert result is None


async def test_test_connection_non_200() -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 404
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_connection(HOST, DEFAULT_PORT)
    assert result == "cannot_connect"


async def test_test_connection_wrong_body() -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="NOT OK")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_connection(HOST, DEFAULT_PORT)
    assert result == "cannot_connect"


async def test_test_connection_connector_error() -> None:
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError())
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_connection(HOST, DEFAULT_PORT)
    assert result == "cannot_connect"


async def test_test_connection_timeout() -> None:
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=TimeoutError())
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_connection(HOST, DEFAULT_PORT)
    assert result == "timeout"


async def test_test_connection_unknown_error() -> None:
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=RuntimeError("unexpected"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await _test_connection(HOST, DEFAULT_PORT)
    assert result == "unknown"


# ---------------------------------------------------------------------------
# Config flow — async_step_user
# ---------------------------------------------------------------------------


async def test_step_user_shows_form(hass: HomeAssistant) -> None:
    result = await _start_flow(hass)
    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "step_id" in result
    assert result["step_id"] == "user"
    assert "errors" in result
    assert result["errors"] == {}


async def test_step_user_success(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ), patch("custom_components.sunriser.async_setup_entry", return_value=True):
        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
            result["flow_id"],
            {CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        )

    assert "type" in result
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "data" in result
    assert result["data"][CONF_HOST] == HOST
    assert "data" in result
    assert result["data"][CONF_PORT] == DEFAULT_PORT


async def test_step_user_cannot_connect(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.sunriser.config_flow._test_connection",
        return_value="cannot_connect",
    ):
        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
            result["flow_id"],
            {CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        )

    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "errors" in result
    assert require_value(result["errors"])["base"] == "cannot_connect"


async def test_step_user_duplicate_aborts(hass: HomeAssistant) -> None:
    """Submitting the same host:port as an existing entry aborts as already_configured."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{HOST}:{DEFAULT_PORT}",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
    )
    existing.add_to_hass(hass)

    result = await _start_flow(hass)
    assert "type" in result
    assert result["type"] == FlowResultType.FORM

    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ):
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
            result["flow_id"],
            {CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        )

    assert "type" in result
    assert result["type"] == FlowResultType.ABORT
    assert "reason" in result
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Reconfigure flow
# ---------------------------------------------------------------------------

NEW_HOST = "192.168.0.200"


async def _start_reconfigure_flow(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


async def test_reconfigure_shows_form_prefilled(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
    )
    entry.add_to_hass(hass)

    result = await _start_reconfigure_flow(hass, entry)
    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "step_id" in result
    assert result["step_id"] == "reconfigure"
    assert "data_schema" in result
    schema = require_value(result["data_schema"])
    host_keys = [k for k in schema.schema if str(k) == CONF_HOST]
    assert host_keys[0].default() == HOST


async def test_reconfigure_success(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ), patch("custom_components.sunriser.async_setup_entry", return_value=True):
        result = await _start_reconfigure_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
            result["flow_id"],
            {CONF_HOST: NEW_HOST, CONF_PORT: DEFAULT_PORT},
        )

    assert "type" in result
    assert result["type"] == FlowResultType.ABORT
    assert "reason" in result
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == NEW_HOST


async def test_reconfigure_cannot_connect(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sunriser.config_flow._test_connection",
        return_value="cannot_connect",
    ):
        result = await _start_reconfigure_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
            result["flow_id"],
            {CONF_HOST: NEW_HOST, CONF_PORT: DEFAULT_PORT},
        )

    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "errors" in result
    assert require_value(result["errors"])["base"] == "cannot_connect"


# ---------------------------------------------------------------------------
# DHCP discovery flow
# ---------------------------------------------------------------------------

DHCP_INFO = DhcpServiceInfo(
    ip="192.168.0.50",
    hostname="sunriser",
    macaddress="aabbccddeeff",
)


async def _start_dhcp_flow(hass: HomeAssistant) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DHCP_INFO,
    )


async def test_dhcp_shows_confirm_form(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ):
        result = await _start_dhcp_flow(hass)

    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "step_id" in result
    assert result["step_id"] == "dhcp_confirm"


async def test_dhcp_confirm_creates_entry(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ), patch("custom_components.sunriser.async_setup_entry", return_value=True):
        result = await _start_dhcp_flow(hass)
        result = await hass.config_entries.flow.async_configure(  # pyright: ignore[reportUnknownMemberType]
            result["flow_id"], {}
        )

    assert "type" in result
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "data" in result
    assert result["data"][CONF_HOST] == "192.168.0.50"
    assert "data" in result
    assert result["data"][CONF_PORT] == DEFAULT_PORT


async def test_dhcp_aborts_if_already_configured(hass: HomeAssistant) -> None:
    """DHCP flow for a known MAC aborts as already_configured (same IP, no data change)."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="aabbccddeeff",
        data={CONF_HOST: "192.168.0.50", CONF_PORT: DEFAULT_PORT},
    )
    existing.add_to_hass(hass)

    with patch("custom_components.sunriser.async_setup_entry", return_value=True):
        result = await _start_dhcp_flow(hass)

    assert "type" in result
    assert result["type"] == FlowResultType.ABORT
    assert "reason" in result
    assert result["reason"] == "already_configured"


async def test_dhcp_updates_host_if_ip_changed(hass: HomeAssistant) -> None:
    """DHCP with a new IP for a known MAC updates the entry's host and reloads."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="aabbccddeeff",
        data={CONF_HOST: "192.168.0.10", CONF_PORT: DEFAULT_PORT},  # old IP
    )
    existing.add_to_hass(hass)

    with patch("custom_components.sunriser.async_setup_entry", return_value=True):
        result = await _start_dhcp_flow(hass)  # DHCP_INFO has ip="192.168.0.50"

    assert "type" in result
    assert result["type"] == FlowResultType.ABORT
    assert "reason" in result
    assert result["reason"] == "already_configured"
    assert existing.data[CONF_HOST] == "192.168.0.50"


async def test_dhcp_aborts_on_cannot_connect(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.sunriser.config_flow._test_connection",
        return_value="cannot_connect",
    ):
        result = await _start_dhcp_flow(hass)

    assert "type" in result
    assert result["type"] == FlowResultType.ABORT
    assert "reason" in result
    assert result["reason"] == "cannot_connect"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_flow_shows_form(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "step_id" in result
    assert result["step_id"] == "init"


async def test_options_flow_saves_interval(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 60},
    )

    assert "type" in result
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "data" in result
    assert result["data"][CONF_SCAN_INTERVAL] == 60


async def test_options_flow_uses_existing_interval(hass: HomeAssistant) -> None:
    """The form schema default must reflect the stored option, not DEFAULT_SCAN_INTERVAL."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCAN_INTERVAL: 120},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "data_schema" in result
    schema = require_value(result["data_schema"])
    # Find the CONF_SCAN_INTERVAL key in the schema and verify its default is 120
    scan_keys = [k for k in schema.schema if str(k) == CONF_SCAN_INTERVAL]
    assert len(scan_keys) == 1
    assert scan_keys[0].default() == 120


async def test_options_flow_invalid_reboot_time(hass: HomeAssistant) -> None:
    """Submitting a bad reboot time returns a form with the invalid_time error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(  # pyright: ignore[reportUnknownMemberType]  # Incomplete upstream annotations.
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 60,
            CONF_SCHEDULED_REBOOT: True,
            CONF_REBOOT_TIME: "25:00",
        },
    )

    assert "type" in result
    assert result["type"] == FlowResultType.FORM
    assert "errors" in result
    assert require_value(result["errors"]).get(CONF_REBOOT_TIME) == "invalid_time"
