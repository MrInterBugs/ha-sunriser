"""Regression cases found while reviewing the simplified integration."""

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.helpers import entity_registry, issue_registry
from homeassistant.helpers.issue_registry import IssueSeverity

from custom_components.sunriser.const import DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.number import SunRiserPWMFixedNumber
from custom_components.sunriser.select import SunRiserPWMManagerSelect
from tests.conftest import FAKE_CONFIG, FAKE_STATE


@pytest.fixture
async def loaded_entry(hass, mock_config_entry):
    async def load(coord):
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
    hass, loaded_entry, platform, suffix, service, value, expected
):
    coord = loaded_entry.runtime_data
    eid = entity_registry.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{loaded_entry.entry_id}_pwm_1_{suffix}"
    )
    before = hass.states.get(eid).state
    assert before != expected
    with aioresponses() as http:
        http.put(f"{coord.base_url}/", status=200)
        await hass.services.async_call(
            platform, service, {"entity_id": eid, **value}, blocking=True
        )
    assert hass.states.get(eid).state == expected


async def test_failed_config_control_keeps_published_value(hass, loaded_entry):
    coord = loaded_entry.runtime_data
    eid = entity_registry.async_get(hass).async_get_entity_id(
        "number", DOMAIN, f"{loaded_entry.entry_id}_pwm_1_fixed"
    )
    before = hass.states.get(eid).state
    with aioresponses() as http:
        http.put(f"{coord.base_url}/", status=500)
        with pytest.raises(aiohttp.ClientResponseError):
            await hass.services.async_call(
                "number", "set_value", {"entity_id": eid, "value": 750}, blocking=True
            )
    assert hass.states.get(eid).state == before
    assert coord.config["pwm#1#fixed"] == 500


async def test_raw_sensor_is_not_advertised_as_temperature(hass, loaded_entry):
    coord = loaded_entry.runtime_data
    eid = entity_registry.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_sensor_AABBCCDDEEFF"
    )
    assert hass.states.get(eid).attributes["device_class"] == "temperature"
    coord.config["sensors#sensor#AABBCCDDEEFF#unit"] = 0
    coord.async_set_updated_data(dict(coord.data))
    state = hass.states.get(eid)
    assert "device_class" not in state.attributes
    assert "unit_of_measurement" not in state.attributes
    assert float(state.state) == 21.1
    coord.config["sensors#sensor#AABBCCDDEEFF#unit"] = 1
    coord.async_set_updated_data(dict(coord.data))
    assert hass.states.get(eid).attributes["device_class"] == "temperature"
    assert hass.states.get(eid).attributes["unit_of_measurement"] == "°C"


async def test_success_after_reload_clears_persisted_offline_issue(hass, coordinator):
    own = f"device_unreachable_{coordinator._entry_id}"
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


async def test_removing_entry_clears_its_offline_issue(hass, loaded_entry):
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


async def test_weekplanner_accepts_unassigned_null_days(coordinator):
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
