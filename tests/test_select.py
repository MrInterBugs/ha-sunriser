# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser select platform (pwm#X#manager)."""

import pytest
from tests.conftest import DOMAIN, ENTRY_ID
from custom_components.sunriser.select import (
    SunRiserPWMManagerSelect,
    async_setup_entry,
)

# ---------------------------------------------------------------------------
# async_setup_entry — entity creation
# ---------------------------------------------------------------------------


async def test_setup_creates_select_for_active_channels(
    hass, coordinator, mock_config_entry
):
    """One select per active channel (pwm1, pwm2, pwm4); pwm3 is unused."""
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    assert len(added) == 3
    pwm_nums = {e._pwm_num for e in added}
    assert pwm_nums == {1, 2, 4}


async def test_setup_excludes_unused_channels(hass, coordinator, mock_config_entry):
    """Channels with empty color string must not get a select entity."""
    mock_config_entry.runtime_data = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    assert all(e._pwm_num != 3 for e in added)


# ---------------------------------------------------------------------------
# current_option
# ---------------------------------------------------------------------------


def _make_select(coordinator, mock_config_entry, pwm_num=1):
    return SunRiserPWMManagerSelect(coordinator, mock_config_entry, pwm_num)


def test_current_option_dayplanner(coordinator, mock_config_entry):
    """pwm1 has manager=1 → 'dayplanner'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.current_option == "dayplanner"


def test_current_option_none(coordinator, mock_config_entry):
    """pwm2 has manager=0 → 'none'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=2)
    assert sel.current_option == "none"


def test_current_option_weekplanner(coordinator, mock_config_entry):
    """pwm4 has manager=2 → 'weekplanner'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=4)
    assert sel.current_option == "weekplanner"


def test_current_option_missing_key_defaults_to_none(coordinator, mock_config_entry):
    """Missing manager key (returns None from config) should fall back to 'none'."""
    del coordinator.config["pwm#1#manager"]
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.current_option == "none"


def test_current_option_fixed(coordinator, mock_config_entry):
    coordinator.config["pwm#1#manager"] = 3
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.current_option == "fixed"


# ---------------------------------------------------------------------------
# async_select_option
# ---------------------------------------------------------------------------


async def test_select_option_writes_correct_key(coordinator, mock_config_entry):
    """Selecting 'weekplanner' should PUT pwm#1#manager=2."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    await sel.async_select_option("weekplanner")
    coordinator.async_set_config.assert_awaited_once_with({"pwm#1#manager": 2})


async def test_select_option_updates_local_config(coordinator, mock_config_entry):
    """After selecting, coordinator.config must reflect the new value immediately."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    await sel.async_select_option("fixed")
    assert coordinator.config["pwm#1#manager"] == 3


async def test_select_option_none_writes_zero(coordinator, mock_config_entry):
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    await sel.async_select_option("none")
    coordinator.async_set_config.assert_awaited_once_with({"pwm#1#manager": 0})


async def test_select_option_dayplanner_writes_one(coordinator, mock_config_entry):
    sel = _make_select(coordinator, mock_config_entry, pwm_num=2)
    await sel.async_select_option("dayplanner")
    coordinator.async_set_config.assert_awaited_once_with({"pwm#2#manager": 1})


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_unique_id(coordinator, mock_config_entry):
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.unique_id == f"{ENTRY_ID}_pwm_1_manager"


def test_name_includes_channel_name(coordinator, mock_config_entry):
    """Entity name should be '<channel name> Manager'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.name == "TROPIC 4500K Manager"


def test_options_list_is_complete(coordinator, mock_config_entry):
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert set(sel.options) == {"none", "dayplanner", "weekplanner", "fixed"}
