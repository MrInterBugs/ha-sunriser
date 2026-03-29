# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser switch platform."""

from unittest.mock import AsyncMock, patch
import datetime

from tests.conftest import DOMAIN, ENTRY_ID, FAKE_STATE
from custom_components.sunriser.const import PWM_MAX
from custom_components.sunriser.switch import (
    SunRiserDSTAutoSwitch,
    SunRiserMaintenanceSwitch,
    SunRiserSwitch,
    SunRiserTimelapseSwitch,
    async_setup_entry,
)

# ---------------------------------------------------------------------------
# async_setup_entry — entity creation
# ---------------------------------------------------------------------------


async def test_setup_creates_maintenance_switch(hass, coordinator, mock_config_entry):
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    types = [type(e).__name__ for e in added]
    assert "SunRiserMaintenanceSwitch" in types


async def test_setup_creates_pwm_switch_for_onoff_channels(
    hass, coordinator, mock_config_entry
):
    """pwm2 has onoff=True → becomes a SunRiserSwitch."""
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    pwm_switches = [e for e in added if isinstance(e, SunRiserSwitch)]
    assert len(pwm_switches) == 1  # only pwm2
    assert pwm_switches[0]._pwm_num == 2


async def test_setup_excludes_unused_onoff_channels(
    hass, coordinator, mock_config_entry
):
    """Unused channels (empty color) are excluded even if onoff=True."""
    coordinator.config["pwm#3#onoff"] = True  # still unused (empty color)
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    pwm_switches = [e for e in added if isinstance(e, SunRiserSwitch)]
    assert len(pwm_switches) == 1  # pwm2 still present
    assert pwm_switches[0]._pwm_num != 3


# ---------------------------------------------------------------------------
# SunRiserMaintenanceSwitch
# ---------------------------------------------------------------------------


def _make_maint(coordinator, mock_config_entry):
    return SunRiserMaintenanceSwitch(coordinator, mock_config_entry)


def test_maintenance_is_off_when_service_mode_zero(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "service_mode": 0}
    switch = _make_maint(coordinator, mock_config_entry)
    assert switch.is_on is False


def test_maintenance_is_on_when_service_mode_nonzero(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "service_mode": 1711234567}
    switch = _make_maint(coordinator, mock_config_entry)
    assert switch.is_on is True


def test_maintenance_is_off_when_data_none(coordinator, mock_config_entry):
    coordinator.data = None
    switch = _make_maint(coordinator, mock_config_entry)
    assert switch.is_on is False


async def test_maintenance_turn_on(coordinator, mock_config_entry):
    switch = _make_maint(coordinator, mock_config_entry)
    await switch.async_turn_on()
    coordinator.async_set_service_mode.assert_awaited_once_with(True)
    coordinator.async_request_refresh.assert_awaited_once()


async def test_maintenance_turn_off(coordinator, mock_config_entry):
    switch = _make_maint(coordinator, mock_config_entry)
    await switch.async_turn_off()
    coordinator.async_set_service_mode.assert_awaited_once_with(False)
    coordinator.async_request_refresh.assert_awaited_once()


def test_maintenance_unique_id(coordinator, mock_config_entry):
    switch = _make_maint(coordinator, mock_config_entry)
    assert switch.unique_id == f"{ENTRY_ID}_maintenance"


# ---------------------------------------------------------------------------
# SunRiserSwitch (PWM on/off channel)
# ---------------------------------------------------------------------------


def _make_switch(coordinator, mock_config_entry, pwm_num=2):
    return SunRiserSwitch(coordinator, mock_config_entry, pwm_num)


def test_pwm_switch_is_on(coordinator, mock_config_entry):
    # FAKE_STATE pwms["2"] = 1000
    switch = _make_switch(coordinator, mock_config_entry, pwm_num=2)
    assert switch.is_on is True


def test_pwm_switch_is_off(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "pwms": {"1": 0, "2": 0, "3": 0, "4": 0}}
    switch = _make_switch(coordinator, mock_config_entry, pwm_num=2)
    assert switch.is_on is False


async def test_pwm_switch_turn_on_sends_max(coordinator, mock_config_entry):
    switch = _make_switch(coordinator, mock_config_entry, pwm_num=2)
    await switch.async_turn_on()
    coordinator.async_set_pwms.assert_awaited_once_with({"2": PWM_MAX})
    coordinator.async_request_refresh.assert_awaited_once()


async def test_pwm_switch_turn_off_sends_zero(coordinator, mock_config_entry):
    switch = _make_switch(coordinator, mock_config_entry, pwm_num=2)
    await switch.async_turn_off()
    coordinator.async_set_pwms.assert_awaited_once_with({"2": 0})
    coordinator.async_request_refresh.assert_awaited_once()


def test_pwm_switch_unique_id(coordinator, mock_config_entry):
    switch = _make_switch(coordinator, mock_config_entry, pwm_num=2)
    assert switch.unique_id == f"{ENTRY_ID}_pwm_2"


# ---------------------------------------------------------------------------
# SunRiserTimelapseSwitch
# ---------------------------------------------------------------------------


def _make_timelapse(coordinator, mock_config_entry):
    return SunRiserTimelapseSwitch(coordinator, mock_config_entry)


async def test_setup_creates_timelapse_switch(hass, coordinator, mock_config_entry):
    coordinator.async_set_timewarp = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    types = [type(e).__name__ for e in added]
    assert "SunRiserTimelapseSwitch" in types


def test_timelapse_is_on_when_timewarp_set(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "timewarp": 1}
    switch = _make_timelapse(coordinator, mock_config_entry)
    assert switch.is_on is True


def test_timelapse_is_off_when_timewarp_zero(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "timewarp": 0}
    switch = _make_timelapse(coordinator, mock_config_entry)
    assert switch.is_on is False


def test_timelapse_is_off_when_data_none(coordinator, mock_config_entry):
    coordinator.data = None
    switch = _make_timelapse(coordinator, mock_config_entry)
    assert switch.is_on is False


async def test_timelapse_turn_on(coordinator, mock_config_entry):
    coordinator.async_set_timewarp = AsyncMock()
    switch = _make_timelapse(coordinator, mock_config_entry)
    await switch.async_turn_on()
    coordinator.async_set_timewarp.assert_awaited_once_with(True)
    coordinator.async_request_refresh.assert_awaited_once()


async def test_timelapse_turn_off(coordinator, mock_config_entry):
    coordinator.async_set_timewarp = AsyncMock()
    switch = _make_timelapse(coordinator, mock_config_entry)
    await switch.async_turn_off()
    coordinator.async_set_timewarp.assert_awaited_once_with(False)
    coordinator.async_request_refresh.assert_awaited_once()


def test_timelapse_unique_id(coordinator, mock_config_entry):
    switch = _make_timelapse(coordinator, mock_config_entry)
    assert switch.unique_id == f"{ENTRY_ID}_timelapse"


# ---------------------------------------------------------------------------
# SunRiserDSTAutoSwitch
# ---------------------------------------------------------------------------


def _make_dst(coordinator, mock_config_entry):
    return SunRiserDSTAutoSwitch(coordinator, mock_config_entry)


async def test_setup_creates_dst_switch(hass, coordinator, mock_config_entry):
    coordinator.async_set_dst_auto_track = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    types = [type(e).__name__ for e in added]
    assert "SunRiserDSTAutoSwitch" in types


def test_dst_is_on_reflects_coordinator_flag(coordinator, mock_config_entry):
    coordinator._dst_auto_track = True
    switch = _make_dst(coordinator, mock_config_entry)
    assert switch.is_on is True


def test_dst_is_off_reflects_coordinator_flag(coordinator, mock_config_entry):
    coordinator._dst_auto_track = False
    switch = _make_dst(coordinator, mock_config_entry)
    assert switch.is_on is False


async def test_dst_turn_on(coordinator, mock_config_entry):
    coordinator.async_set_dst_auto_track = AsyncMock()
    switch = _make_dst(coordinator, mock_config_entry)
    switch.hass = None  # async_write_ha_state needs hass; stub it
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_on()
    coordinator.async_set_dst_auto_track.assert_awaited_once_with(True)


async def test_dst_turn_off(coordinator, mock_config_entry):
    coordinator.async_set_dst_auto_track = AsyncMock()
    switch = _make_dst(coordinator, mock_config_entry)
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_off()
    coordinator.async_set_dst_auto_track.assert_awaited_once_with(False)


def test_dst_unique_id(coordinator, mock_config_entry):
    switch = _make_dst(coordinator, mock_config_entry)
    assert switch.unique_id == f"{ENTRY_ID}_dst_auto_track"


async def test_dst_restores_on_state_from_last_state(
    hass, coordinator, mock_config_entry
):
    """async_added_to_hass restores auto-track when last state was ON."""
    from homeassistant.const import STATE_ON
    from unittest.mock import MagicMock

    coordinator.async_set_dst_auto_track = AsyncMock()
    switch = _make_dst(coordinator, mock_config_entry)

    last_state = MagicMock()
    last_state.state = STATE_ON

    with patch.object(
        switch, "async_get_last_state", AsyncMock(return_value=last_state)
    ):
        with patch.object(switch, "async_write_ha_state"):
            # super().async_added_to_hass() requires entity to be in hass; patch it
            with patch(
                "homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass",
                AsyncMock(),
            ):
                await switch.async_added_to_hass()

    coordinator.async_set_dst_auto_track.assert_awaited_once_with(True)


async def test_dst_does_not_restore_when_last_state_off(
    hass, coordinator, mock_config_entry
):
    """async_added_to_hass does not enable auto-track when last state was OFF."""
    from homeassistant.const import STATE_OFF
    from unittest.mock import MagicMock

    coordinator.async_set_dst_auto_track = AsyncMock()
    switch = _make_dst(coordinator, mock_config_entry)

    last_state = MagicMock()
    last_state.state = STATE_OFF

    with patch.object(
        switch, "async_get_last_state", AsyncMock(return_value=last_state)
    ):
        with patch(
            "homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass",
            AsyncMock(),
        ):
            await switch.async_added_to_hass()

    coordinator.async_set_dst_auto_track.assert_not_awaited()


async def test_dst_does_not_restore_when_no_last_state(
    hass, coordinator, mock_config_entry
):
    """async_added_to_hass does not enable auto-track when there is no prior state."""
    coordinator.async_set_dst_auto_track = AsyncMock()
    switch = _make_dst(coordinator, mock_config_entry)

    with patch.object(switch, "async_get_last_state", AsyncMock(return_value=None)):
        with patch(
            "homeassistant.helpers.update_coordinator.CoordinatorEntity.async_added_to_hass",
            AsyncMock(),
        ):
            await switch.async_added_to_hass()

    coordinator.async_set_dst_auto_track.assert_not_awaited()
