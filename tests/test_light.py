# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the SunRiser light platform."""

from homeassistant.components.light import ATTR_BRIGHTNESS
from tests.conftest import DOMAIN, ENTRY_ID, FAKE_STATE
from custom_components.sunriser.light import SunRiserLight, async_setup_entry

# ---------------------------------------------------------------------------
# async_setup_entry — entity filtering
# ---------------------------------------------------------------------------


async def test_setup_creates_lights_for_dimmable_channels(
    hass, coordinator, mock_config_entry
):
    """Channels that are not on/off and not unused become light entities."""
    hass.data.setdefault(DOMAIN, {})[ENTRY_ID] = coordinator

    added = []
    await async_setup_entry(hass, mock_config_entry, lambda e: added.extend(e))

    names = {e._attr_name for e in added}
    # pwm1 = "TROPIC 4500K" (dimmable), pwm4 = "SKY 6500K" (dimmable)
    # pwm2 = on/off switch → excluded, pwm3 = unused → excluded
    assert len(added) == 2
    assert all(isinstance(e, SunRiserLight) for e in added)


# ---------------------------------------------------------------------------
# SunRiserLight properties
# ---------------------------------------------------------------------------


def _make_light(coordinator, mock_config_entry, pwm_num=1):
    return SunRiserLight(coordinator, mock_config_entry, pwm_num)


def test_is_on_when_pwm_nonzero(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.is_on is True  # FAKE_STATE pwms["1"] = 500


def test_is_on_false_when_pwm_zero(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "pwms": {"1": 0, "2": 0, "3": 0, "4": 0}}
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.is_on is False


def test_brightness_nonzero(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.brightness > 0


def test_brightness_max_at_pwm_1000(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "pwms": {"1": 1000}}
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.brightness == 255


def test_brightness_zero_at_pwm_zero(coordinator, mock_config_entry):
    coordinator.data = {**FAKE_STATE, "pwms": {"1": 0}}
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.brightness == 0


def test_unique_id(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.unique_id == f"{ENTRY_ID}_pwm_1"


def test_device_info_set(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    assert light.device_info is not None


# ---------------------------------------------------------------------------
# SunRiserLight actions
# ---------------------------------------------------------------------------


async def test_turn_on_sends_brightness(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_on(**{ATTR_BRIGHTNESS: 128})

    coordinator.async_set_pwms.assert_awaited_once()
    call_args = coordinator.async_set_pwms.call_args[0][0]
    assert "1" in call_args
    assert 0 < call_args["1"] < 1000


async def test_turn_on_defaults_to_full_brightness(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_on()

    coordinator.async_set_pwms.assert_awaited_once()
    call_args = coordinator.async_set_pwms.call_args[0][0]
    assert call_args["1"] == 1000  # 255 → 1000


async def test_turn_off_sends_zero(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_off()

    coordinator.async_set_pwms.assert_awaited_once_with({"1": 0})
    coordinator.async_request_refresh.assert_awaited_once()


async def test_turn_on_triggers_refresh(coordinator, mock_config_entry):
    light = _make_light(coordinator, mock_config_entry, pwm_num=1)
    await light.async_turn_on()
    coordinator.async_request_refresh.assert_awaited_once()
