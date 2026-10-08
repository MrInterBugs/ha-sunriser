"""Regression cases found while reviewing the simplified integration."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry, issue_registry
from homeassistant.helpers.issue_registry import IssueSeverity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.const import DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.number import SunRiserPWMFixedNumber
from custom_components.sunriser.select import SunRiserPWMManagerSelect
from tests.conftest import FAKE_CONFIG, FAKE_STATE
from tests.typing import require_value


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> AsyncIterator[MockConfigEntry]:
    async def load(coord: SunRiserCoordinator) -> None:
        coord.config = dict(FAKE_CONFIG)

    mock_config_entry.add_to_hass(hass)
    with (
        patch.object(SunRiserCoordinator, "async_load_device_config", load),
        patch.object(
            SunRiserCoordinator,
            "_async_update_data",
            AsyncMock(return_value={**FAKE_STATE, "ok": True}),
        ),
        patch.object(
            SunRiserPWMFixedNumber, "_attr_entity_registry_enabled_default", True
        ),
        patch.object(
            SunRiserPWMManagerSelect, "_attr_entity_registry_enabled_default", True
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        yield mock_config_entry
        if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is not None:
            await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize(
    "platform,suffix,service,value,expected",
    [
        ("number", "fixed", "set_value", {"value": 750}, "750.0"),
        ("select", "manager", "select_option", {"option": "fixed"}, "fixed"),
    ],
)
async def test_successful_config_control_publishes_ha_state_immediately(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    platform: str,
    suffix: str,
    service: str,
    value: Any,
    expected: str,
) -> None:
    coord = loaded_entry.runtime_data
    eid = entity_registry.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{loaded_entry.entry_id}_pwm_1_{suffix}"
    )
    before = require_value(hass.states.get(require_value(eid))).state
    assert before != expected
    with aioresponses() as http:
        http.put(f"{coord.base_url}/", status=200)
        await hass.services.async_call(
            platform, service, {"entity_id": eid, **value}, blocking=True
        )
    assert require_value(hass.states.get(require_value(eid))).state == expected


async def test_failed_config_control_keeps_published_value(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    coord = loaded_entry.runtime_data
    eid = entity_registry.async_get(hass).async_get_entity_id(
        "number", DOMAIN, f"{loaded_entry.entry_id}_pwm_1_fixed"
    )
    before = require_value(hass.states.get(require_value(eid))).state
    with aioresponses() as http:
        http.put(f"{coord.base_url}/", status=500)
        with pytest.raises(aiohttp.ClientResponseError):
            await hass.services.async_call(
                "number", "set_value", {"entity_id": eid, "value": 750}, blocking=True
            )
    assert require_value(hass.states.get(require_value(eid))).state == before
    assert coord.config["pwm#1#fixed"] == 500


async def test_raw_sensor_is_not_advertised_as_temperature(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    coord = loaded_entry.runtime_data
    eid = entity_registry.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_sensor_AABBCCDDEEFF"
    )
    assert (
        require_value(hass.states.get(require_value(eid))).attributes["device_class"]
        == "temperature"
    )
    coord.config["sensors#sensor#AABBCCDDEEFF#unit"] = 0
    coord.async_set_updated_data(dict(coord.data))
    state = require_value(hass.states.get(require_value(eid)))
    assert "device_class" not in state.attributes
    assert "unit_of_measurement" not in state.attributes
    assert float(state.state) == 21.1
    coord.config["sensors#sensor#AABBCCDDEEFF#unit"] = 1
    coord.async_set_updated_data(dict(coord.data))
    assert (
        require_value(hass.states.get(require_value(eid))).attributes["device_class"]
        == "temperature"
    )
    assert (
        require_value(hass.states.get(require_value(eid))).attributes[
            "unit_of_measurement"
        ]
        == "°C"
    )


async def test_success_after_reload_clears_persisted_offline_issue(
    hass: HomeAssistant, coordinator: SunRiserCoordinator
) -> None:
    own = f"device_unreachable_{coordinator.entry_id}"
    other = "device_unreachable_other_controller"
    for issue in (own, other):
        issue_registry.async_create_issue(
            hass,
            DOMAIN,
            issue,
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="device_unreachable",
        )
    # A reloaded coordinator has no in-memory record of the previous failures.
    assert coordinator._consecutive_failures == 0
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    await coordinator._async_refresh_state()
    issues = issue_registry.async_get(hass).issues
    assert (DOMAIN, own) not in issues
    assert (DOMAIN, other) in issues


async def test_removing_entry_clears_its_offline_issue(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    issue = f"device_unreachable_{loaded_entry.entry_id}"
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        issue,
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key="device_unreachable",
    )
    await hass.config_entries.async_remove(loaded_entry.entry_id)
    assert (DOMAIN, issue) not in issue_registry.async_get(hass).issues


async def test_weekplanner_accepts_unassigned_null_days(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.async_get_config = AsyncMock(
        return_value={"weekplanner#programs#1": [None, 2, None, 4]}
    )
    schedule = await coordinator.async_get_weekplanner(1)
    assert schedule == {
        "sunday": None,
        "monday": 2,
        "tuesday": None,
        "wednesday": 4,
        "thursday": None,
        "friday": None,
        "saturday": None,
        "default": None,
    }
