"""Regression coverage for exports, device identity, cache ordering and discovery."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers import issue_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser import _SET_DAYPLANNER_SCHEMA
from custom_components.sunriser.const import DOMAIN
from custom_components.sunriser.select import SunRiserPWMManagerSelect
from custom_components.sunriser.sensor import (
    async_setup_entry as setup_sensors,
    SunRiserTemperatureSensor,
)
from tests.test_service_routing import controllers


@pytest.mark.parametrize(
    "service,method",
    [
        ("backup", "async_get_backup"),
        ("download_factory_backup", "async_get_factory_backup"),
        ("download_firmware", "async_get_firmware"),
        ("download_bootload", "async_get_bootload"),
    ],
)
async def test_exports_do_not_overwrite_other_controllers(
    hass, controllers, tmp_path, service, method
):
    for index, (_, coord, _) in enumerate(controllers):
        setattr(coord, method, AsyncMock(return_value=f"controller-{index}".encode()))
    fixed = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    with (
        patch("custom_components.sunriser.dt_util.now", return_value=fixed),
        patch.object(
            hass.config, "path", side_effect=lambda name: str(tmp_path / name)
        ),
    ):
        results = []
        for _, _, device in controllers:
            results.append(
                await hass.services.async_call(
                    DOMAIN,
                    service,
                    {"device_id": device.id},
                    blocking=True,
                    return_response=True,
                )
            )
    assert (
        results[0]["path"] != results[1]["path"]
    ), "Second controller overwrote the first export"
    assert Path(results[0]["path"]).read_bytes() == b"controller-0"


async def test_dhcp_does_not_duplicate_manual_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="192.0.2.1:80", data={"host": "192.0.2.1", "port": 80}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo(
                ip="192.0.2.1", hostname="sunriser", macaddress="aabbccddeeff"
            ),
        )
    assert result["type"] == FlowResultType.ABORT


async def test_manual_does_not_duplicate_dhcp_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="aabbccddeeff", data={"host": "192.0.2.1", "port": 80}
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.sunriser.config_flow._test_connection", return_value=None
        ),
        patch("custom_components.sunriser.async_setup_entry", return_value=False),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.1", "port": 80}
        )
    assert result["type"] == FlowResultType.ABORT


@pytest.mark.parametrize("invalid_time", ["99:99", "12:60", "25:00"])
def test_schedule_rejects_invalid_clock_times(invalid_time):
    with pytest.raises(vol.Invalid):
        _SET_DAYPLANNER_SCHEMA(
            {"pwm": 1, "markers": [{"time": invalid_time, "percent": 50}]}
        )


async def test_new_temperature_is_not_published_without_scaling_metadata(
    hass, coordinator, mock_config_entry
):
    mock_config_entry.runtime_data = coordinator
    added = []
    await setup_sensors(
        hass, mock_config_entry, lambda entities: added.extend(entities)
    )
    coordinator.async_get_state = AsyncMock(
        return_value={**coordinator.data, "sensors": {"NEW_ROM": [1, 251]}}
    )
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(side_effect=TimeoutError())
    await coordinator.async_refresh()
    assert (
        "sensors#sensor#NEW_ROM#unitcomma"
        in coordinator.async_get_config.await_args.args[0]
    )
    assert not any(
        isinstance(e, SunRiserTemperatureSensor) and e._rom == "NEW_ROM" for e in added
    )
    assert coordinator.sensor_value("NEW_ROM") is None
    metadata = {
        "sensors#sensor#NEW_ROM#name": "New probe",
        "sensors#sensor#NEW_ROM#unit": 1,
        "sensors#sensor#NEW_ROM#unitcomma": 1,
    }
    coordinator.async_get_config = AsyncMock(return_value=metadata)
    await coordinator.async_refresh()
    new = next(
        e
        for e in added
        if isinstance(e, SunRiserTemperatureSensor) and e._rom == "NEW_ROM"
    )
    assert new.native_value == 25.1
    assert new.native_unit_of_measurement == "°C"
    assert new.name == "New probe"


async def test_one_controller_recovery_does_not_clear_other_controller_issue(
    hass, controllers
):
    import aiohttp

    first, second = controllers[0][1], controllers[1][1]
    for coord in (first, second):

        coord.data = {"uptime": 10}
        coord.async_get_state = AsyncMock(side_effect=aiohttp.ClientConnectionError())
        for _ in range(3):
            await coord.async_refresh()
    first.async_get_state = AsyncMock(return_value={"uptime": 20})
    await first.async_refresh()
    assert second._consecutive_failures == 3
    issues = issue_registry.async_get(hass).issues
    assert any(
        domain == DOMAIN for domain, _ in issues
    ), "Recovering controller A removed the offline warning for B"


@pytest.mark.parametrize(
    "platform,suffix",
    [("light", ""), ("switch", ""), ("number", "_fixed"), ("select", "_manager")],
)
async def test_startup_retires_previously_registered_inactive_channel(
    hass, coordinator, mock_config_entry, platform, suffix
):
    from homeassistant.helpers import entity_registry
    from importlib import import_module

    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = coordinator
    registry = entity_registry.async_get(hass)
    old = registry.async_get_or_create(
        platform,
        DOMAIN,
        f"{mock_config_entry.entry_id}_pwm_3{suffix}",
        config_entry=mock_config_entry,
    )
    assert coordinator.pwm_is_unused(3)
    await import_module(f"custom_components.sunriser.{platform}").async_setup_entry(
        hass, mock_config_entry, lambda entities: None
    )
    assert (
        registry.async_get(old.entity_id) is None
    ), "An inactive channel left a stale registered entity after reload"


async def test_repeated_exports_same_controller_same_second_are_distinct(
    hass, controllers, tmp_path
):
    coord, device = controllers[0][1:]
    coord.async_get_backup = AsyncMock(side_effect=[b"first", b"second"])
    with (
        patch(
            "custom_components.sunriser.dt_util.now",
            return_value=datetime(2026, 10, 8, tzinfo=timezone.utc),
        ),
        patch.object(
            hass.config, "path", side_effect=lambda name: str(tmp_path / name)
        ),
    ):
        first = await hass.services.async_call(
            DOMAIN,
            "backup",
            {"device_id": device.id},
            blocking=True,
            return_response=True,
        )
        second = await hass.services.async_call(
            DOMAIN,
            "backup",
            {"device_id": device.id},
            blocking=True,
            return_response=True,
        )
    assert first["path"] != second["path"]
    assert Path(first["path"]).read_bytes() == b"first"
    assert Path(second["path"]).read_bytes() == b"second"


async def test_export_never_truncates_existing_file(hass, controllers, tmp_path):
    from homeassistant.exceptions import HomeAssistantError

    coord, device = controllers[0][1:]
    coord.async_get_backup = AsyncMock(return_value=b"replacement")
    destination = tmp_path / "existing.msgpack"
    destination.write_bytes(b"original")
    with patch.object(hass.config, "path", return_value=str(destination)):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN, "backup", {"device_id": device.id}, blocking=True
            )
    assert destination.read_bytes() == b"original"


async def test_dhcp_adopts_manual_entry_then_updates_its_address(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.0.2.1:80",
        data={"host": "192.0.2.1", "port": 80},
        options={"scan_interval": 60},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.sunriser.async_setup_entry", return_value=False):
        for ip in ("192.0.2.1", "192.0.2.2"):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_DHCP},
                data=DhcpServiceInfo(
                    ip=ip, hostname="sunriser", macaddress="aabbccddeeff"
                ),
            )
            assert result["type"] == FlowResultType.ABORT
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.unique_id == "aabbccddeeff"
    assert entry.data["host"] == "192.0.2.2"
    assert entry.options == {"scan_interval": 60}


@pytest.mark.parametrize("conflict", [False, True])
async def test_reconfigure_updates_manual_identity_or_rejects_duplicate(hass, conflict):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="192.0.2.1:80", data={"host": "192.0.2.1", "port": 80}
    )
    entry.add_to_hass(hass)
    if conflict:
        MockConfigEntry(
            domain=DOMAIN,
            unique_id="aabbccddeeff",
            data={"host": "192.0.2.2", "port": 80},
        ).add_to_hass(hass)
    with (
        patch(
            "custom_components.sunriser.config_flow._test_connection", return_value=None
        ),
        patch("custom_components.sunriser.async_setup_entry", return_value=False),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.2", "port": 80}
        )
    assert result["reason"] == (
        "already_configured" if conflict else "reconfigure_successful"
    )
    assert entry.unique_id == ("192.0.2.1:80" if conflict else "192.0.2.2:80")


async def test_manual_entry_added_while_dhcp_confirmation_open(hass):
    with patch(
        "custom_components.sunriser.config_flow._test_connection", return_value=None
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo(
                ip="192.0.2.1", hostname="sunriser", macaddress="aabbccddeeff"
            ),
        )
    MockConfigEntry(
        domain=DOMAIN, unique_id="192.0.2.1:80", data={"host": "192.0.2.1", "port": 80}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.ABORT
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize("valid_time", ["00:00", "8:00", "23:59", "24:00"])
def test_schedule_accepts_clock_times_and_end_of_day(valid_time):
    result = _SET_DAYPLANNER_SCHEMA(
        {"pwm": 1, "markers": [{"time": valid_time, "percent": 50}]}
    )
    assert result["markers"][0]["time"] == valid_time


@pytest.mark.parametrize(
    "source", [config_entries.SOURCE_USER, config_entries.SOURCE_RECONFIGURE]
)
async def test_endpoint_claimed_while_connection_check_is_pending(hass, source):
    context = {"source": source}
    if source == config_entries.SOURCE_RECONFIGURE:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="192.0.2.1:80",
            data={"host": "192.0.2.1", "port": 80},
        )
        entry.add_to_hass(hass)
        context["entry_id"] = entry.entry_id

    async def connect(host, port):
        MockConfigEntry(
            domain=DOMAIN, unique_id="aabbccddeeff", data={"host": host, "port": port}
        ).add_to_hass(hass)
        return None

    with patch(
        "custom_components.sunriser.config_flow._test_connection", side_effect=connect
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context=context)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.2", "port": 80}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    if source == config_entries.SOURCE_RECONFIGURE:
        assert entry.data["host"] == "192.0.2.1"


async def test_dhcp_address_change_cannot_claim_another_configured_endpoint(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="aabbccddeeff", data={"host": "192.0.2.1", "port": 80}
    )
    entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN, unique_id="192.0.2.2:80", data={"host": "192.0.2.2", "port": 80}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip="192.0.2.2", hostname="sunriser", macaddress="aabbccddeeff"
        ),
    )
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.1"


def test_known_temperature_disappears_from_state(coordinator):
    coordinator.data = {**coordinator.data, "sensors": {}}
    assert coordinator.sensor_value("AABBCCDDEEFF") is None
