# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for SunRiserCoordinator — HTTP calls mocked via aioresponses."""

import aiohttp
import logging
import msgpack
import pytest
from unittest.mock import AsyncMock
from aioresponses import aioresponses
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
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
# async_load_device_config
# ---------------------------------------------------------------------------


async def test_load_device_config(coord):
    base_resp = {
        "hostname": "testunit",
        "save_version": "1.005",
        "factory_version": "1.005",
        "model": "SunRiser 10",
        "pwm_count": 4,
        "name": "SunRiser",
        "model_id": "sr10",
    }
    pwm_resp = {
        "pwm#1#name": None,
        "pwm#1#onoff": False,
        "pwm#1#max": None,
        "pwm#1#color": "4500k",
        "pwm#2#name": None,
        "pwm#2#onoff": True,
        "pwm#2#max": None,
        "pwm#2#color": "pump",
        "pwm#3#name": None,
        "pwm#3#onoff": False,
        "pwm#3#max": None,
        "pwm#3#color": "",
        "pwm#4#name": None,
        "pwm#4#onoff": False,
        "pwm#4#max": None,
        "pwm#4#color": "6500k",
    }

    with aioresponses() as m:
        m.post(f"{BASE}/", body=_pack(base_resp))
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.post(f"{BASE}/", body=_pack(pwm_resp))
        await coord.async_load_device_config()

    assert coord.config["hostname"] == "testunit"
    assert coord.config["pwm_count"] == 4
    assert coord.config["pwm#1#color"] == "4500k"


async def test_load_device_config_derives_pwm_count_from_state(coord):
    """When pwm_count is None in config, derive it from len(state['pwms'])."""
    base_resp = {
        "hostname": "testunit",
        "save_version": None,
        "factory_version": "1.005",
        "model": "SunRiser 10",
        "pwm_count": None,  # <-- None
        "name": "SunRiser",
        "model_id": "sr10",
    }
    state_with_pwms = {"pwms": {"1": 0, "2": 0, "3": 0}, "uptime": 1, "service_mode": 0}
    pwm_resp = {f"pwm#{i}#name": None for i in range(1, 4)}
    pwm_resp.update({f"pwm#{i}#onoff": False for i in range(1, 4)})
    pwm_resp.update({f"pwm#{i}#max": None for i in range(1, 4)})
    pwm_resp.update({f"pwm#{i}#color": "4500k" for i in range(1, 4)})

    with aioresponses() as m:
        m.post(f"{BASE}/", body=_pack(base_resp))
        m.get(f"{BASE}/state", body=_pack(state_with_pwms))
        m.post(f"{BASE}/", body=_pack(pwm_resp))
        await coord.async_load_device_config()

    assert coord.config["pwm_count"] == 3


async def test_load_device_config_with_password(hass, mock_config_entry):
    """When a password is set, a login POST is sent before reading config."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={"host": HOST, "port": DEFAULT_PORT, "password": "secret"},
        options={},
    )
    coord = SunRiserCoordinator(hass, entry)
    try:
        base_resp = {
            "hostname": "h",
            "save_version": None,
            "factory_version": "1",
            "model": "sr",
            "pwm_count": 1,
            "name": "SR",
            "model_id": "sr8",
        }
        pwm_resp = {
            "pwm#1#name": None,
            "pwm#1#onoff": False,
            "pwm#1#max": None,
            "pwm#1#color": "6500k",
        }
        state = {"pwms": {"1": 0}, "uptime": 1, "service_mode": 0}

        with aioresponses() as m:
            m.post(f"{BASE}/", body=b"OK")  # auth
            m.post(f"{BASE}/", body=_pack(base_resp))  # config
            m.get(f"{BASE}/state", body=_pack(state))
            m.post(f"{BASE}/", body=_pack(pwm_resp))
            await coord.async_load_device_config()

        assert coord.config["hostname"] == "h"
    finally:
        await coord.async_close()


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------


async def test_update_data_success(coord):
    coord.config = dict(FAKE_CONFIG)
    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.get(f"{BASE}/weather", body=_pack([None, {"weather_program_id": 1}]))
        data = await coord._async_update_data()
    assert data["uptime"] == 12345
    assert data["weather"] == [None, {"weather_program_id": 1}]


async def test_update_data_fetches_new_sensor_config(coord):
    """New DS1820 ROMs appearing in state trigger a config fetch."""
    coord.config = dict(FAKE_CONFIG)
    # Remove sensor config so it looks new
    del coord.config["sensors#sensor#AABBCCDDEEFF#name"]

    sensor_cfg = {
        "sensors#sensor#AABBCCDDEEFF#name": "Water Temp",
        "sensors#sensor#AABBCCDDEEFF#unit": 1,
        "sensors#sensor#AABBCCDDEEFF#unitcomma": 1,
    }
    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.post(f"{BASE}/", body=_pack(sensor_cfg))
        m.get(f"{BASE}/weather", body=_pack([]))
        data = await coord._async_update_data()

    assert coord.config["sensors#sensor#AABBCCDDEEFF#name"] == "Water Temp"


async def test_update_data_client_error_raises_update_failed(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=aiohttp.ClientConnectionError("down"))
        with pytest.raises(UpdateFailed, match="Error communicating"):
            await coord._async_update_data()


async def test_update_data_unexpected_error_raises_update_failed(coord):
    with aioresponses() as m:
        m.get(f"{BASE}/state", exception=ValueError("boom"))
        with pytest.raises(UpdateFailed, match="Unexpected error"):
            await coord._async_update_data()


async def test_update_data_sensor_config_fetch_error_logs_warning(coord, caplog):
    """If the sensor config POST fails, log a warning but don't crash."""
    coord.config = dict(FAKE_CONFIG)
    del coord.config["sensors#sensor#AABBCCDDEEFF#name"]

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.post(f"{BASE}/", exception=aiohttp.ClientConnectionError("down"))
        m.get(f"{BASE}/weather", body=_pack([]))
        with caplog.at_level(logging.WARNING, logger="custom_components.sunriser"):
            data = await coord._async_update_data()

    assert data["uptime"] == 12345  # main data still returned despite the fetch failure
    assert "Could not fetch sensor config" in caplog.text


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

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        m.get(f"{BASE}/weather", exception=aiohttp.ClientConnectionError("down"))
        with caplog.at_level(logging.DEBUG, logger="custom_components.sunriser"):
            data = await coord._async_update_data()

    assert data["weather"] == {}
    assert "Could not fetch weather data" in caplog.text


async def test_update_data_weather_unexpected_error_logs_debug_and_returns_empty_weather(
    coord, monkeypatch, caplog
):
    coord.config = dict(FAKE_CONFIG)
    monkeypatch.setattr(
        coord, "async_get_weather", AsyncMock(side_effect=ValueError("boom"))
    )

    with aioresponses() as m:
        m.get(f"{BASE}/state", body=_pack(FAKE_STATE))
        with caplog.at_level(logging.DEBUG, logger="custom_components.sunriser"):
            data = await coord._async_update_data()

    assert data["weather"] == {}
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


def test_sensor_value_raw_unit(coordinator):
    coordinator.config["sensors#sensor#AABBCCDDEEFF#unitcomma"] = 0
    val = coordinator.sensor_value("AABBCCDDEEFF")
    assert val == 211.0


def test_device_info_has_identifiers(coordinator):
    info = coordinator.device_info
    assert (DOMAIN, ENTRY_ID) in info["identifiers"]


def test_pwm_count_property(coordinator):
    assert coordinator.pwm_count == 4


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
