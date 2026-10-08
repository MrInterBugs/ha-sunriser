# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for SunRiserCoordinator — HTTP calls mocked via aioresponses."""

import aiohttp
import logging
import msgpack
import pytest
from unittest.mock import AsyncMock
from aioresponses import aioresponses
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from tests.conftest import ENTRY_ID, FAKE_CONFIG, FAKE_STATE, HOST
from custom_components.sunriser.const import DEFAULT_PORT, DOMAIN
from custom_components.sunriser.coordinator import SunRiserCoordinator

BASE = f"http://{HOST}:{DEFAULT_PORT}"


def _pack(data):
    return msgpack.packb(data, use_bin_type=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def coord(hass, mock_config_entry):
    coordinator = SunRiserCoordinator(hass, mock_config_entry)
    try:
        yield coordinator
    finally:
        await coordinator.async_close()


# ---------------------------------------------------------------------------
# hass.data bridge — DST auto-track survives same-session reloads
# ---------------------------------------------------------------------------


async def test_coordinator_init_restores_dst_auto_track_from_hass_data(
    hass, mock_config_entry
):
    """Constructor reads _dst_auto_track from the hass.data bridge and pops the key."""
    hass.data[DOMAIN] = {f"{ENTRY_ID}_dst_auto_track": True}
    coord = SunRiserCoordinator(hass, mock_config_entry)
    try:
        assert coord._dst_auto_track is True
        # Key is consumed so a second construction does not inherit the flag.
        assert f"{ENTRY_ID}_dst_auto_track" not in hass.data.get(DOMAIN, {})
    finally:
        await coord.async_close()


async def test_coordinator_init_dst_auto_track_defaults_false(hass, mock_config_entry):
    """Constructor defaults _dst_auto_track to False when no bridge key is present."""
    coord = SunRiserCoordinator(hass, mock_config_entry)
    try:
        assert coord._dst_auto_track is False
    finally:
        await coord.async_close()


async def test_coordinator_init_ignores_other_hass_data_keys(hass, mock_config_entry):
    """Bridge key for a different entry_id is not consumed."""
    hass.data[DOMAIN] = {"other_entry_id_dst_auto_track": True}
    coord = SunRiserCoordinator(hass, mock_config_entry)
    try:
        assert coord._dst_auto_track is False
        assert hass.data[DOMAIN]["other_entry_id_dst_auto_track"] is True
    finally:
        await coord.async_close()


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------


async def test_update_data_state_tick_resets_timewarp_when_absent(coord):
    """timewarp is reset to 0 each state tick so stale ON state doesn't linger."""

    coord.config = dict(FAKE_CONFIG)
    coord.data = {**FAKE_STATE, "ok": True, "weather": [], "timewarp": 1}

    with aioresponses() as m:
        m.get(
            f"{BASE}/state", body=_pack(FAKE_STATE)
        )  # device omits timewarp when inactive
        data = await coord._async_update_data()

    assert data["timewarp"] == 0


async def test_update_data_client_error_raises_update_failed(coord):

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("down"))
        with pytest.raises(UpdateFailed, match="Error communicating"):
            await coord._async_update_data()


async def test_update_data_unexpected_error_raises_update_failed(coord):

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=ValueError("boom"))
        with pytest.raises(UpdateFailed, match="Error communicating"):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# Grace period — stale data returned for transient failures
# ---------------------------------------------------------------------------


async def test_grace_period_returns_stale_data_on_first_failure(coord, caplog):
    """First failure with existing data should return stale data, not raise."""

    coord.data = dict(FAKE_STATE)

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("blip"))
        with caplog.at_level(logging.DEBUG, logger="custom_components.sunriser"):
            data = await coord._async_update_data()

    assert data is not coord.data
    assert coord._consecutive_failures == 1
    assert "returning stale data" in caplog.text


async def test_grace_period_returns_stale_data_on_second_failure(coord):
    """Second consecutive failure should still return stale data."""

    coord.data = dict(FAKE_STATE)
    coord._consecutive_failures = 1

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("blip"))
        data = await coord._async_update_data()

    assert data is not coord.data
    assert coord._consecutive_failures == 2


async def test_grace_period_raises_on_third_failure(coord):
    """Third consecutive failure should raise UpdateFailed."""

    coord.data = dict(FAKE_STATE)
    coord._consecutive_failures = 2

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("down"))
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    assert coord._consecutive_failures == 3


async def test_grace_period_raises_immediately_with_no_prior_data(coord):
    """If there is no prior data, raise UpdateFailed immediately on any failure."""

    assert coord.data is None

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("down"))
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


async def test_grace_period_resets_on_success(coord):
    """A successful poll resets the consecutive failure counter."""

    coord.config = dict(FAKE_CONFIG)
    coord._consecutive_failures = 2

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.get(f"{BASE}/weather", body=_pack([]))
        m.post(f"{BASE}/", body=_pack(FAKE_CONFIG))
        await coord._async_update_data()

    assert coord._consecutive_failures == 0


async def test_recovery_after_unavailable_logs_info(coord, caplog):
    """Recovery after >= FAILURE_GRACE failures logs at INFO."""
    coord.config = dict(FAKE_CONFIG)
    coord._consecutive_failures = coord._FAILURE_GRACE

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        with caplog.at_level(logging.INFO, logger="custom_components.sunriser"):
            await coord._async_refresh_state()

    assert "available again" in caplog.text
    assert coord._consecutive_failures == 0


async def test_repair_issue_created_at_failure_grace(coord):
    """A repair issue is created when failures reach _FAILURE_GRACE."""

    coord.data = dict(FAKE_STATE)
    coord._consecutive_failures = coord._FAILURE_GRACE - 1

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("down"))
        from unittest.mock import patch

        with patch(
            "custom_components.sunriser.coordinator.async_create_issue"
        ) as mock_create:
            with pytest.raises(Exception):
                await coord._async_update_data()

    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs.args[2] == f"device_unreachable_{ENTRY_ID}"
    assert call_kwargs.kwargs["translation_placeholders"]["host"] == coord.host


async def test_repair_issue_not_created_before_grace(coord):
    """No repair issue fires during the grace period (failures < _FAILURE_GRACE)."""

    coord.data = dict(FAKE_STATE)
    coord._consecutive_failures = 0

    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("blip"))
        from unittest.mock import patch

        with patch(
            "custom_components.sunriser.coordinator.async_create_issue"
        ) as mock_create:
            await coord._async_update_data()

    mock_create.assert_not_called()


async def test_repair_issue_deleted_on_recovery(coord):
    """Repair issue is deleted when the device comes back after >= FAILURE_GRACE failures."""
    coord.config = dict(FAKE_CONFIG)
    coord._consecutive_failures = coord._FAILURE_GRACE

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        from unittest.mock import patch

        with patch(
            "custom_components.sunriser.coordinator.async_delete_issue"
        ) as mock_delete:
            await coord._async_refresh_state()

    mock_delete.assert_called_once()
    assert mock_delete.call_args.args[2] == f"device_unreachable_{ENTRY_ID}"


async def test_successful_poll_also_clears_repairs_from_previous_coordinator(coord):
    """A successful read also clears an issue persisted before a reload."""
    coord.config = dict(FAKE_CONFIG)
    coord._consecutive_failures = 1  # below FAILURE_GRACE

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        from unittest.mock import patch

        with patch(
            "custom_components.sunriser.coordinator.async_delete_issue"
        ) as mock_delete:
            await coord._async_refresh_state()

    mock_delete.assert_called_once()


async def test_update_data_weather_failure_keeps_stale_weather(coord, caplog):

    coord.data = {**FAKE_STATE, "weather": [{"weather_program_id": 3}]}

    with aioresponses() as m:
        m.get(f"{BASE}/weather", exception=aiohttp.ClientConnectionError("down"))
        with caplog.at_level(logging.DEBUG, logger="custom_components.sunriser"):
            data = await coord._async_refresh_weather(dict(coord.data))

    assert data["weather"] == [{"weather_program_id": 3}]
    assert "Could not fetch weather data" in caplog.text


async def test_async_get_weather_returns_first_msgpack_object(coord):
    weather = [None, {"weather_program_id": 3, "clouds_state": 0}]
    body = _pack(weather) + _pack({"ignored": True})

    with aioresponses() as m:
        m.get(f"{BASE}/weather", body=body)
        result = await coord.async_get_weather()

    assert result == weather


async def test_async_get_weather_returns_empty_list_for_empty_stream(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/weather", body=b"")
        result = await coord.async_get_weather()

    assert result == []


async def test_update_data_weather_client_error_logs_debug_and_returns_empty_weather(
    coord, caplog
):

    coord.config = dict(FAKE_CONFIG)
    coord.data = {**FAKE_STATE, "ok": True, "weather": []}

    with aioresponses() as m:
        m.get(f"{BASE}/weather", exception=aiohttp.ClientConnectionError("down"))
        with caplog.at_level(logging.DEBUG, logger="custom_components.sunriser"):
            data = await coord._async_refresh_weather(dict(coord.data))

    assert data["weather"] == []
    assert "Could not fetch weather data" in caplog.text


async def test_update_data_weather_unexpected_error_logs_debug_and_returns_empty_weather(
    coord, monkeypatch, caplog
):

    coord.config = dict(FAKE_CONFIG)
    coord.data = {**FAKE_STATE, "ok": True, "weather": []}
    monkeypatch.setattr(
        coord, "async_get_weather", AsyncMock(side_effect=ValueError("boom"))
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.sunriser"):
        data = await coord._async_refresh_weather(dict(coord.data))

    assert data["weather"] == []
    assert "Unexpected error fetching weather data" in caplog.text


# ---------------------------------------------------------------------------
# async_set_config / async_set_service_mode / async_set_pwms
# ---------------------------------------------------------------------------


async def test_async_set_config(coord):
    """save_version must be injected into every config PUT (device requirement)."""
    coord.config["factory_version"] = "1.005"
    with aioresponses() as m:
        m.put(f"{BASE}/", status=200)
        await coord.async_set_config({"pwm#1#color": "6500k"})

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/"))][0].kwargs["data"], raw=False
    )
    assert sent["pwm#1#color"] == "6500k"
    assert sent["save_version"] == "1.005"


async def test_async_set_service_mode_on(coord):
    """service_mode must be integer 1, not boolean True — device returns 500 for booleans."""
    with aioresponses() as m:
        m.put(f"{BASE}/state", status=200)
        await coord.async_set_service_mode(True)

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/state"))][0].kwargs["data"], raw=False
    )
    assert sent["service_mode"] == 1
    assert type(sent["service_mode"]) is int


async def test_async_set_service_mode_off(coord):
    """service_mode must be integer 0, not boolean False."""
    with aioresponses() as m:
        m.put(f"{BASE}/state", status=200)
        await coord.async_set_service_mode(False)

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/state"))][0].kwargs["data"], raw=False
    )
    assert sent["service_mode"] == 0
    assert type(sent["service_mode"]) is int


async def test_async_set_pwms(coord):
    with aioresponses() as m:
        m.put(f"{BASE}/state", status=200)
        await coord.async_set_pwms({"1": 750})

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/state"))][0].kwargs["data"], raw=False
    )
    assert sent["pwms"] == {"1": 750}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def test_pwm_name_uses_color(coordinator):
    assert "4500K" in coordinator.pwm_name(1)


def test_pwm_name_falls_back_to_pwm_number(coordinator):
    # pwm#3 has empty color → no name in COLOR_NAMES
    coordinator.config["pwm#3#color"] = "nonexistent_id"
    assert "3" in coordinator.pwm_name(3)


def test_pwm_is_onoff_true(coordinator):
    assert coordinator.pwm_is_onoff(2) is True


def test_pwm_is_onoff_false(coordinator):
    assert coordinator.pwm_is_onoff(1) is False


def test_pwm_manager_returns_configured_value(coordinator):
    assert coordinator.pwm_manager(4) == 2


def test_pwm_manager_defaults_to_zero_when_missing(coordinator):
    coordinator.config["pwm#4#manager"] = None
    assert coordinator.pwm_manager(4) == 0


def test_pwm_is_unused_empty_color(coordinator):
    assert coordinator.pwm_is_unused(3) is True


def test_pwm_is_unused_active_channel(coordinator):
    assert coordinator.pwm_is_unused(1) is False


def test_pwm_value_returns_value(coordinator):
    assert coordinator.pwm_value(1) == 500


def test_pwm_value_returns_zero_when_no_data(coordinator):
    coordinator.data = None
    assert coordinator.pwm_value(1) == 0


def test_sensor_name(coordinator):
    assert coordinator.sensor_name("AABBCCDDEEFF") == "Water Temp"


def test_sensor_name_fallback(coordinator):
    assert coordinator.sensor_name("UNKNOWN") == "UNKNOWN"


def test_sensor_unit(coordinator):
    assert coordinator.sensor_unit("AABBCCDDEEFF") == 1


def test_sensor_unitcomma(coordinator):
    assert coordinator.sensor_unitcomma("AABBCCDDEEFF") == 1


def test_sensor_value_celsius(coordinator):
    val = coordinator.sensor_value("AABBCCDDEEFF")
    assert abs(val - 21.1) < 0.01


def test_sensor_value_returns_none_when_no_data(coordinator):
    coordinator.data = None
    assert coordinator.sensor_value("AABBCCDDEEFF") is None


def test_sensor_value_returns_none_for_missing_rom(coordinator):
    assert coordinator.sensor_value("MISSING") is None


def test_weather_program_name_returns_none_when_program_id_is_none(coordinator):
    assert coordinator.weather_program_name(None) is None


def test_weather_program_name_returns_name_when_loaded(coordinator):
    coordinator.config["weather#setup#1#name"] = "Reef Day"
    assert coordinator.weather_program_name(1) == "Reef Day"


def test_sensor_value_raw_unit(coordinator):
    coordinator.config["sensors#sensor#AABBCCDDEEFF#unitcomma"] = 0
    val = coordinator.sensor_value("AABBCCDDEEFF")
    assert val == 211.0


def test_device_info_has_identifiers(coordinator):
    info = coordinator.device_info
    assert (DOMAIN, ENTRY_ID) in info["identifiers"]


def test_pwm_count_property(coordinator):
    assert coordinator.pwm_count == 4


# ---------------------------------------------------------------------------
# async_set_timewarp
# ---------------------------------------------------------------------------


async def test_async_set_timewarp_on(coord):
    """timewarp=1 (integer) must be sent — boolean True would cause a 500."""
    with aioresponses() as m:
        m.put(f"{BASE}/state", status=200)
        await coord.async_set_timewarp(True)

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/state"))][0].kwargs["data"], raw=False
    )
    assert sent["timewarp"] == 1
    assert type(sent["timewarp"]) is int


async def test_async_set_timewarp_off(coord):
    """timewarp=0 (integer) must be sent — boolean False would cause a 500."""
    with aioresponses() as m:
        m.put(f"{BASE}/state", status=200)
        await coord.async_set_timewarp(False)

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/state"))][0].kwargs["data"], raw=False
    )
    assert sent["timewarp"] == 0
    assert type(sent["timewarp"]) is int


# ---------------------------------------------------------------------------
# async_set_dst_auto_track
# ---------------------------------------------------------------------------


async def test_async_set_dst_auto_track_true_syncs_immediately(coordinator):
    """Enabling DST auto-track fires an immediate PUT / with current summertime."""
    from unittest.mock import patch
    import datetime

    fixed_dst = datetime.timedelta(hours=1)
    with patch("custom_components.sunriser.coordinator.dt_util.now") as mock_now:
        mock_now.return_value.dst.return_value = fixed_dst
        await coordinator.async_set_dst_auto_track(True)

    assert coordinator._dst_auto_track is True
    assert coordinator._last_known_dst is True
    coordinator.async_set_config.assert_awaited_once_with({"summertime": 1})
    assert coordinator.config["summertime"] == 1


async def test_async_set_dst_auto_track_true_no_dst(coordinator):
    """Enabling DST auto-track in non-DST timezone sends summertime=0."""
    from unittest.mock import patch
    import datetime

    with patch("custom_components.sunriser.coordinator.dt_util.now") as mock_now:
        mock_now.return_value.dst.return_value = datetime.timedelta(0)
        await coordinator.async_set_dst_auto_track(True)

    coordinator.async_set_config.assert_awaited_once_with({"summertime": 0})
    assert coordinator._last_known_dst is False


async def test_async_set_dst_auto_track_false_does_not_sync(coordinator):
    """Disabling DST auto-track should not make any HTTP call."""
    await coordinator.async_set_dst_auto_track(False)

    assert coordinator._dst_auto_track is False
    coordinator.async_set_config.assert_not_awaited()


# ---------------------------------------------------------------------------
# _async_update_data — DST sync pending branch
# ---------------------------------------------------------------------------


def test_pwm_count_fallback(coordinator):
    coordinator.config["pwm_count"] = None
    assert coordinator.pwm_count == 8


# ---------------------------------------------------------------------------
# async_reboot / async_get_backup / async_restore / async_get_errors / async_get_log
# ---------------------------------------------------------------------------


async def test_async_reboot(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/reboot", status=200)
        await coord.async_reboot()
    assert ("GET", URL(f"{BASE}/reboot")) in m.requests


async def test_async_get_backup_returns_bytes(coord):
    payload = b"\x82\xa4name\xa8SunRiser"
    with aioresponses() as m:
        m.get(f"{BASE}/backup", body=payload)
        result = await coord.async_get_backup()
    assert result == payload


async def test_async_restore_sends_bytes(coord):
    payload = b"\x82\xa4name\xa8SunRiser"
    with aioresponses() as m:
        m.put(f"{BASE}/restore", status=200)
        await coord.async_restore(payload)
    sent = m.requests[("PUT", URL(f"{BASE}/restore"))][0].kwargs["data"]
    assert sent == payload


async def test_async_get_errors_returns_text(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/errors", body=b"error line 1\nerror line 2")
        result = await coord.async_get_errors()
    assert "error line 1" in result


async def test_async_get_log_returns_text(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/log", body=b"log entry 1\nlog entry 2")
        result = await coord.async_get_log()
    assert "log entry 1" in result


# ---------------------------------------------------------------------------
# async_get_dayplanner / async_set_dayplanner
# ---------------------------------------------------------------------------


async def test_async_get_dayplanner_parses_flat_array(coord):
    """Flat [daymin, percent, ...] array in config cache is converted to sorted marker dicts."""
    # 08:00 → 480 mins, 20:30 → 1230 mins
    coord.config["dayplanner#marker#1"] = [1230, 75, 480, 50]
    result = await coord.async_get_dayplanner(1)

    assert result == [
        {"time": "08:00", "percent": 50},
        {"time": "20:30", "percent": 75},
    ]


async def test_async_get_dayplanner_returns_empty_list_when_unset(coord):
    """None or missing key returns an empty list."""
    with aioresponses() as m:
        m.post(f"{BASE}/", body=_pack({"dayplanner#marker#2": None}))
        result = await coord.async_get_dayplanner(2)

    assert result == []


async def test_async_get_dayplanner_skips_none_entries(coord):
    """None values in the flat marker array are silently skipped (device quirk)."""
    coord.config["dayplanner#marker#3"] = [None, 50, 480, None, 600, 75]
    result = await coord.async_get_dayplanner(3)

    assert result == [{"time": "10:00", "percent": 75}]


async def test_async_set_dayplanner_sends_flat_array(coord):
    """Marker dicts are converted back to flat [daymin, percent, ...] and PUT."""
    coord.config["factory_version"] = "1.005"
    markers = [{"time": "08:00", "percent": 50}, {"time": "20:30", "percent": 75}]
    with aioresponses() as m:
        m.put(f"{BASE}/", status=200)
        await coord.async_set_dayplanner(1, markers)

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/"))][0].kwargs["data"], raw=False
    )
    assert sent["dayplanner#marker#1"] == [480, 50, 1230, 75]


# ---------------------------------------------------------------------------
# async_check_ok
# ---------------------------------------------------------------------------


async def test_async_check_ok_returns_true(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/ok", body=b"OK")
        result = await coord.async_check_ok()
    assert result is True


async def test_async_check_ok_returns_false_on_wrong_body(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/ok", body=b"NOT OK")
        result = await coord.async_check_ok()
    assert result is False


async def test_async_check_ok_returns_false_on_error(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/ok", exception=aiohttp.ClientConnectionError("down"))
        result = await coord.async_check_ok()
    assert result is False


async def test_update_data_includes_ok_true(coord):
    """_async_update_data stores ok=True when state fetch succeeds."""

    coord.config = dict(FAKE_CONFIG)
    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.get(f"{BASE}/weather", body=_pack([]))
        m.post(f"{BASE}/", body=_pack(FAKE_CONFIG))
        data = await coord._async_update_data()
    assert data["ok"] is True


async def test_update_data_ok_false_when_state_fails_within_grace(coord):
    """ok=False when the state fetch fails but stale data is returned within the grace period."""

    coord.config = dict(FAKE_CONFIG)
    coord.data = {**FAKE_STATE, "ok": True}

    coord._consecutive_failures = 1
    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("down"))
        data = await coord._async_update_data()
    assert data["ok"] is False


# ---------------------------------------------------------------------------
# async_get_factory_backup / async_get_firmware / async_get_bootload
# ---------------------------------------------------------------------------


async def test_async_get_factory_backup_returns_bytes(coord):
    payload = b"\x82\xa4name\xa8SunRiser"
    with aioresponses() as m:
        m.get(f"{BASE}/factorybackup", body=payload)
        result = await coord.async_get_factory_backup()
    assert result == payload


async def test_async_get_firmware_returns_bytes(coord):
    payload = b"\x81\xa8filename\xaafw_1.005"
    with aioresponses() as m:
        m.get(f"{BASE}/firmware.mp", body=payload)
        result = await coord.async_get_firmware()
    assert result == payload


async def test_async_get_bootload_returns_bytes(coord):
    payload = b"\x81\xa4boot\xa31.0"
    with aioresponses() as m:
        m.get(f"{BASE}/bootload.mp", body=payload)
        result = await coord.async_get_bootload()
    assert result == payload


# ---------------------------------------------------------------------------
# async_factory_reset
# ---------------------------------------------------------------------------


async def test_async_factory_reset_sends_delete(coord):
    with aioresponses() as m:
        m.delete(f"{BASE}/", status=200)
        await coord.async_factory_reset()
    assert ("DELETE", URL(f"{BASE}/")) in m.requests


# ---------------------------------------------------------------------------
# async_get_weekplanner / async_set_weekplanner
# ---------------------------------------------------------------------------


async def test_async_get_weekplanner_parses_array(coord):
    """8-element flat array is mapped to day-name dict."""
    # sun=2, mon..fri=1, sat=2, default=0
    flat = [2, 1, 1, 1, 1, 1, 2, 0]
    with aioresponses() as m:
        m.post(f"{BASE}/", body=_pack({"weekplanner#programs#1": flat}))
        result = await coord.async_get_weekplanner(1)
    assert result == {
        "sunday": 2,
        "monday": 1,
        "tuesday": 1,
        "wednesday": 1,
        "thursday": 1,
        "friday": 1,
        "saturday": 2,
        "default": 0,
    }


async def test_async_get_weekplanner_returns_none_for_unset(coord):
    """None value (key never written) returns all-None dict."""
    with aioresponses() as m:
        m.post(f"{BASE}/", body=_pack({"weekplanner#programs#1": None}))
        result = await coord.async_get_weekplanner(1)
    assert all(v is None for v in result.values())
    assert set(result.keys()) == {
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "default",
    }


async def test_async_set_weekplanner_sends_flat_array(coord):
    coord.config["factory_version"] = "1.005"
    schedule = {
        "sunday": 2,
        "monday": 1,
        "tuesday": 1,
        "wednesday": 1,
        "thursday": 1,
        "friday": 1,
        "saturday": 2,
        "default": 0,
    }
    with aioresponses() as m:
        m.put(f"{BASE}/", status=200)
        await coord.async_set_weekplanner(1, schedule)

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/"))][0].kwargs["data"], raw=False
    )
    assert sent["weekplanner#programs#1"] == [2, 1, 1, 1, 1, 1, 2, 0]


async def test_async_set_weekplanner_missing_days_default_to_zero(coord):
    """Days not in the schedule dict are written as 0."""
    coord.config["factory_version"] = "1.005"
    with aioresponses() as m:
        m.put(f"{BASE}/", status=200)
        await coord.async_set_weekplanner(1, {"monday": 3})

    sent = msgpack.unpackb(
        m.requests[("PUT", URL(f"{BASE}/"))][0].kwargs["data"], raw=False
    )
    assert sent["weekplanner#programs#1"] == [0, 3, 0, 0, 0, 0, 0, 0]


# ---------------------------------------------------------------------------
# Scheduled reboot
# ---------------------------------------------------------------------------


async def test_scheduled_reboot_disabled_skips_setup(hass):
    """When CONF_SCHEDULED_REBOOT=False, no time-change listener is registered."""
    from homeassistant.const import CONF_HOST, CONF_PORT
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sunriser.const import (
        CONF_SCHEDULED_REBOOT,
        DEFAULT_PORT,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="reboot_test",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCHEDULED_REBOOT: False},
    )
    coord = SunRiserCoordinator(hass, entry)
    try:
        assert coord._scheduled_reboot_cancel is None
    finally:
        await coord.async_close()


async def test_scheduled_reboot_invalid_time_logs_warning(hass, caplog):
    """An unparseable reboot time logs a warning and leaves cancel as None."""
    from homeassistant.const import CONF_HOST, CONF_PORT
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sunriser.const import (
        CONF_REBOOT_TIME,
        CONF_SCHEDULED_REBOOT,
        DEFAULT_PORT,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="reboot_test2",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCHEDULED_REBOOT: True, CONF_REBOOT_TIME: "not-a-time"},
    )
    with caplog.at_level(logging.WARNING, logger="custom_components.sunriser"):
        coord = SunRiserCoordinator(hass, entry)
    try:
        assert coord._scheduled_reboot_cancel is None
        assert "invalid scheduled reboot time" in caplog.text
    finally:
        await coord.async_close()


async def test_scheduled_reboot_trigger_fires_on_time_event(hass):
    """The _trigger callback creates a task that eventually calls async_reboot."""
    from homeassistant.const import CONF_HOST, CONF_PORT
    from unittest.mock import AsyncMock, patch
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sunriser.const import (
        CONF_REBOOT_TIME,
        CONF_SCHEDULED_REBOOT,
        DEFAULT_PORT,
        DOMAIN,
    )
    from datetime import datetime
    from homeassistant.helpers.event import async_track_time_change

    captured_trigger = None

    def mock_track(hass_arg, action, **kwargs):
        nonlocal captured_trigger
        captured_trigger = action
        return lambda: None  # return a no-op cancel

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="reboot_test3",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCHEDULED_REBOOT: True, CONF_REBOOT_TIME: "04:00"},
    )
    with patch(
        "custom_components.sunriser.coordinator.async_track_time_change", mock_track
    ):
        coord = SunRiserCoordinator(hass, entry)

    try:
        assert captured_trigger is not None

        reboot_mock = AsyncMock()
        coord.async_reboot = reboot_mock

        # Invoke the trigger callback directly (as HA would at 04:00:00)
        captured_trigger(datetime(2026, 1, 1, 4, 0, 0))
        await hass.async_block_till_done()

        reboot_mock.assert_called_once()
    finally:
        await coord.async_close()


async def test_scheduled_reboot_trigger_calls_reboot(hass):
    """_async_do_scheduled_reboot calls async_reboot."""
    from homeassistant.const import CONF_HOST, CONF_PORT
    from unittest.mock import AsyncMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sunriser.const import (
        CONF_REBOOT_TIME,
        CONF_SCHEDULED_REBOOT,
        DEFAULT_PORT,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="reboot_test3b",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCHEDULED_REBOOT: True, CONF_REBOOT_TIME: "04:00"},
    )
    coord = SunRiserCoordinator(hass, entry)
    try:
        reboot_mock = AsyncMock()
        coord.async_reboot = reboot_mock

        await coord._async_do_scheduled_reboot()

        reboot_mock.assert_called_once()
    finally:
        await coord.async_close()


async def test_scheduled_reboot_failure_is_logged(hass, caplog):
    """If async_reboot raises, the error is logged and does not propagate."""
    from homeassistant.const import CONF_HOST, CONF_PORT
    from unittest.mock import AsyncMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sunriser.const import (
        CONF_REBOOT_TIME,
        CONF_SCHEDULED_REBOOT,
        DEFAULT_PORT,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="reboot_test4",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCHEDULED_REBOOT: True, CONF_REBOOT_TIME: "04:00"},
    )
    coord = SunRiserCoordinator(hass, entry)
    try:
        coord.async_reboot = AsyncMock(side_effect=RuntimeError("device offline"))

        with caplog.at_level(logging.ERROR, logger="custom_components.sunriser"):
            await coord._async_do_scheduled_reboot()

        assert "scheduled reboot failed" in caplog.text
    finally:
        await coord.async_close()


async def test_async_close_cancels_scheduled_reboot(hass):
    """async_close calls the cancel callable and clears _scheduled_reboot_cancel."""
    from homeassistant.const import CONF_HOST, CONF_PORT
    from unittest.mock import MagicMock
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.sunriser.const import (
        CONF_REBOOT_TIME,
        CONF_SCHEDULED_REBOOT,
        DEFAULT_PORT,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="reboot_test5",
        data={CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT},
        options={CONF_SCHEDULED_REBOOT: True, CONF_REBOOT_TIME: "04:00"},
    )
    coord = SunRiserCoordinator(hass, entry)
    assert coord._scheduled_reboot_cancel is not None

    cancel_mock = MagicMock()
    coord._scheduled_reboot_cancel = cancel_mock

    await coord.async_close()

    cancel_mock.assert_called_once()
    assert coord._scheduled_reboot_cancel is None
