# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser number platform (pwm#X#fixed)."""

import pytest
from tests.conftest import DOMAIN, ENTRY_ID
from custom_components.sunriser.number import (
    SunRiserPWMFixedNumber,
    async_setup_entry,
)

# ---------------------------------------------------------------------------
# async_setup_entry — entity creation
# ---------------------------------------------------------------------------


async def test_setup_creates_number_for_active_channels(
    hass, coordinator, mock_config_entry
):
    """One number entity per active channel (pwm1, pwm2, pwm4); pwm3 is unused."""
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    assert len(added) == 3
    assert {e._pwm_num for e in added} == {1, 2, 4}


async def test_setup_excludes_unused_channels(hass, coordinator, mock_config_entry):
    """Channels with empty color string must not get a number entity."""
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    assert all(e._pwm_num != 3 for e in added)


# ---------------------------------------------------------------------------
# native_value
# ---------------------------------------------------------------------------


def _make_number(coordinator, mock_config_entry, pwm_num=1):
    return SunRiserPWMFixedNumber(coordinator, mock_config_entry, pwm_num)


def test_native_value_returns_configured_fixed(coordinator, mock_config_entry):
    """pwm1 has fixed=500 → native_value should be 500.0."""
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    assert num.native_value == 500.0


def test_native_value_none_defaults_to_zero(coordinator, mock_config_entry):
    """pwm2 has fixed=None → native_value should be 0.0."""
    num = _make_number(coordinator, mock_config_entry, pwm_num=2)
    assert num.native_value == 0.0


def test_native_value_zero(coordinator, mock_config_entry):
    """pwm4 has fixed=0 → native_value should be 0.0."""
    num = _make_number(coordinator, mock_config_entry, pwm_num=4)
    assert num.native_value == 0.0


# ---------------------------------------------------------------------------
# async_set_native_value
# ---------------------------------------------------------------------------


async def test_set_native_value_writes_correct_key(coordinator, mock_config_entry):
    """Setting value 750 should PUT pwm#1#fixed=750."""
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    await num.async_set_native_value(750.0)
    coordinator.async_set_config.assert_awaited_once_with({"pwm#1#fixed": 750})


async def test_set_native_value_updates_local_config(coordinator, mock_config_entry):
    """After setting, coordinator.config must reflect the new value immediately."""
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    await num.async_set_native_value(200.0)
    assert coordinator.config["pwm#1#fixed"] == 200


async def test_set_native_value_truncates_to_int(coordinator, mock_config_entry):
    """Float values must be truncated to int before writing."""
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    await num.async_set_native_value(999.9)
    coordinator.async_set_config.assert_awaited_once_with({"pwm#1#fixed": 999})


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_unique_id(coordinator, mock_config_entry):
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    assert num.unique_id == f"{ENTRY_ID}_pwm_1_fixed"


def test_name_includes_channel_name(coordinator, mock_config_entry):
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    assert num._attr_translation_key == "fixed_value"
    assert num._attr_translation_placeholders == {"channel": "TROPIC 4500K"}


def test_range(coordinator, mock_config_entry):
    num = _make_number(coordinator, mock_config_entry, pwm_num=1)
    assert num.native_min_value == 0
    assert num.native_max_value == 1000
    assert num.native_step == 1
