# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser select platform (pwm#X#manager)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.select import (
    SunRiserPWMManagerSelect,
    async_setup_entry,
)
from tests.conftest import ENTRY_ID
from tests.typing import as_async_mock, collect_entities

# ---------------------------------------------------------------------------
# async_setup_entry — entity creation
# ---------------------------------------------------------------------------


async def test_setup_creates_select_for_active_channels(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One select per active channel (pwm1, pwm2, pwm4); pwm3 is unused."""
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    assert len(added) == 3
    pwm_nums = {e._pwm_num for e in added if isinstance(e, SunRiserPWMManagerSelect)}
    assert pwm_nums == {1, 2, 4}


async def test_setup_excludes_unused_channels(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Channels with empty color string must not get a select entity."""
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    assert all(
        isinstance(e, SunRiserPWMManagerSelect) and e._pwm_num != 3 for e in added
    )


# ---------------------------------------------------------------------------
# current_option
# ---------------------------------------------------------------------------


def _make_select(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    pwm_num: int = 1,
) -> SunRiserPWMManagerSelect:
    return SunRiserPWMManagerSelect(coordinator, mock_config_entry, pwm_num)


def test_current_option_dayplanner(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """pwm1 has manager=1 → 'dayplanner'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.current_option == "dayplanner"


def test_current_option_none(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """pwm2 has manager=0 → 'none'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=2)
    assert sel.current_option == "none"


def test_current_option_weekplanner(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """pwm4 has manager=2 → 'weekplanner'."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=4)
    assert sel.current_option == "weekplanner"


def test_current_option_missing_key_defaults_to_none(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """Missing manager key (returns None from config) should fall back to 'none'."""
    del coordinator.config["pwm#1#manager"]
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.current_option == "none"


def test_current_option_fixed(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    coordinator.config["pwm#1#manager"] = 3
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.current_option == "fixed"


# ---------------------------------------------------------------------------
# async_select_option
# ---------------------------------------------------------------------------


async def test_select_option_writes_correct_key(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """Selecting 'weekplanner' should PUT pwm#1#manager=2."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    await sel.async_select_option("weekplanner")
    as_async_mock(coordinator.async_set_config).assert_awaited_once_with(
        {"pwm#1#manager": 2}
    )


async def test_select_option_updates_local_config(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """After selecting, coordinator.config must reflect the new value immediately."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    await sel.async_select_option("fixed")
    assert coordinator.config["pwm#1#manager"] == 3


async def test_select_option_none_writes_zero(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    await sel.async_select_option("none")
    as_async_mock(coordinator.async_set_config).assert_awaited_once_with(
        {"pwm#1#manager": 0}
    )


async def test_select_option_dayplanner_writes_one(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sel = _make_select(coordinator, mock_config_entry, pwm_num=2)
    await sel.async_select_option("dayplanner")
    as_async_mock(coordinator.async_set_config).assert_awaited_once_with(
        {"pwm#2#manager": 1}
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_unique_id(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel.unique_id == f"{ENTRY_ID}_pwm_1_manager"


def test_name_includes_channel_name(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    """Entity name should be '<channel name> Manager' via translation placeholder."""
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert sel._attr_translation_key == "pwm_manager"
    assert sel._attr_translation_placeholders == {"channel": "TROPIC 4500K"}


def test_options_list_is_complete(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    sel = _make_select(coordinator, mock_config_entry, pwm_num=1)
    assert set(sel.options) == {"none", "dayplanner", "weekplanner", "fixed"}
