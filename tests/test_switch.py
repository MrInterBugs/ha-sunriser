# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser switch platform."""

from tests.conftest import DOMAIN, ENTRY_ID, FAKE_STATE
from custom_components.sunriser.const import PWM_MAX
from custom_components.sunriser.switch import (
    SunRiserMaintenanceSwitch,
    SunRiserSwitch,
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
