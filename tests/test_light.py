# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser light platform."""

from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.light import SunRiserLight, async_setup_entry
from tests.conftest import ENTRY_ID, FAKE_STATE
from tests.typing import as_async_mock, collect_entities, require_value

# ---------------------------------------------------------------------------
# async_setup_entry — entity filtering
# ---------------------------------------------------------------------------


async def test_setup_creates_lights_for_dimmable_channels(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Channels that are not on/off and not unused become light entities."""
    mock_config_entry.runtime_data = coordinator

    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))

    # pwm1 = "TROPIC 4500K" (dimmable), pwm4 = "SKY 6500K" (dimmable)
    # pwm2 = on/off switch → excluded, pwm3 = unused → excluded
    assert len(added) == 2
    assert all(isinstance(e, SunRiserLight) for e in added)


# ---------------------------------------------------------------------------
# SunRiserLight properties
# ---------------------------------------------------------------------------


def _make_light(
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
    pwm_num: int = 1,
) -> SunRiserLight:
    return SunRiserLight(coordinator, mock_config_entry, pwm_num)


def test_is_on_when_pwm_nonzero(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.is_on is True  # FAKE_STATE pwms["1"] = 500


def test_is_on_false_when_pwm_zero(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    coordinator.data = {**FAKE_STATE, "pwms": {"1": 0, "2": 0, "3": 0, "4": 0}}
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.is_on is False


def test_brightness_nonzero(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.brightness > 0


def test_brightness_max_at_full_output_readback(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    for value in (1000, 1024):
        coordinator.data = {**FAKE_STATE, "pwms": {"1": value}}
        assert light.brightness == 255


def test_brightness_zero_at_pwm_zero(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    coordinator.data = {**FAKE_STATE, "pwms": {"1": 0}}
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.brightness == 0


def test_unique_id(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.unique_id == f"{ENTRY_ID}_pwm_1"


def test_device_info_set(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.device_info is not None


# ---------------------------------------------------------------------------
# SunRiserLight actions
# ---------------------------------------------------------------------------


async def test_turn_on_sends_brightness(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_on(**{ATTR_BRIGHTNESS: 128})

    as_async_mock(coordinator.async_set_pwms).assert_awaited_once()
    call_args = require_value(as_async_mock(coordinator.async_set_pwms).call_args)[0][0]
    assert "1" in call_args
    assert 0 < call_args["1"] < 1000


async def test_turn_on_defaults_to_full_brightness(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_on()

    as_async_mock(coordinator.async_set_pwms).assert_awaited_once()
    call_args = require_value(as_async_mock(coordinator.async_set_pwms).call_args)[0][0]
    assert call_args["1"] == 1000  # 255 → 1000


async def test_turn_off_sends_zero(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_off()

    as_async_mock(coordinator.async_set_pwms).assert_awaited_once_with({"1": 0})
    as_async_mock(coordinator.async_request_refresh).assert_awaited_once()


async def test_turn_on_triggers_refresh(
    coordinator: SunRiserCoordinator, mock_config_entry: MockConfigEntry
) -> None:
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_on()
    as_async_mock(coordinator.async_request_refresh).assert_awaited_once()
