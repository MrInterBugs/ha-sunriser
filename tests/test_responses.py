# SPDX-License-Identifier: GPL-3.0-or-later
"""Response boundaries and recovery, with synthetic wire data (not hardware captures)."""

from collections.abc import Callable
from typing import Any

import msgpack
import pytest
from aioresponses import aioresponses

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.responses import (
    InvalidResponse,
    decode_config,
    decode_state,
    decode_weather,
)
from tests.conftest import FAKE_CONFIG, FAKE_STATE


@pytest.mark.parametrize("decode", [decode_config, decode_state, decode_weather])
@pytest.mark.parametrize("body", [b"", b"\xc1", b"\x81\xa1x", b"\xa1\xff"])
def test_malformed_wire_data(decode: Callable[[bytes], Any], body: bytes) -> None:
    with pytest.raises(InvalidResponse):
        decode(body)


@pytest.mark.parametrize(
    "decode,value",
    [
        (decode_state, []),
        (decode_state, {1: 2}),
        (decode_state, {"uptime": float("inf")}),
        (decode_state, {"service_mode": True}),
        (decode_state, {"blackout": "off"}),
        (decode_state, {"pwms": []}),
        (decode_state, {"pwms": {"0": 1}}),
        (decode_state, {"pwms": {"1": 1025}}),
        (decode_state, {"pwms": {"1": -1}}),
        (decode_state, {"pwms": {"1": 10, 1: 20}}),
        (decode_state, {"sensors": []}),
        (decode_state, {"sensors": {"probe": [1]}}),
        (decode_state, {"sensors": {"probe": [1, float("nan")]}}),
        (decode_config, []),
        (decode_config, {"pwm_count": 0}),
        (decode_config, {"pwm_count": 11}),
        (decode_config, {"pwm_count": 4.5}),
        (decode_config, {"pwm_count": True}),
        (decode_config, {"factory_version": 1.006}),
        (decode_config, {"pwm#1#fixed": float("nan")}),
        (decode_config, {"pwm#1#onoff": "false"}),
        (decode_config, {"dayplanner#marker#1": {}}),
        (decode_config, {"weekplanner#programs#1": ["invalid"]}),
        (decode_weather, {}),
        (decode_weather, [False]),
        (decode_weather, [None] * 11),
        (decode_weather, [{"weather_program_id": ["invalid"]}]),
        (decode_weather, [{"rainmins": "five"}]),
        (decode_weather, [{"clouds_next_state_tick": float("inf")}]),
    ],
)
def test_reject_invalid_consumed_fields(
    decode: Callable[[bytes], Any], value: Any
) -> None:
    with pytest.raises(InvalidResponse):
        decode(msgpack.packb(value, use_bin_type=True))


def test_optional_and_future_fields_are_preserved() -> None:
    future = {"future": {"arbitrary": [1, "two"]}}
    assert decode_state(msgpack.packb(future)) == future
    config = {**FAKE_CONFIG, **future, "dayplanner#marker#1": [0, 50, None, None]}
    assert decode_config(msgpack.packb(config)) == config
    state = {
        **FAKE_STATE,
        "pwms": {1: 300},
        "sensors": {"offline": None},
        "blackout": False,
    }
    assert decode_state(msgpack.packb(state)) == {**state, "pwms": {"1": 300}}
    weather = [None, {"rainmins": None, **future}]
    assert (
        decode_weather(msgpack.packb(weather) + msgpack.packb({"ignored": True}))
        == weather
    )
    assert decode_weather(msgpack.packb([])) == []
    with pytest.raises(InvalidResponse, match="trailing"):
        decode_state(msgpack.packb({}) + msgpack.packb({}))


async def test_invalid_state_keeps_snapshot_then_recovers(
    coordinator: SunRiserCoordinator,
) -> None:
    before = dict(coordinator.data or {})
    with aioresponses() as http:
        http.get(
            f"{coordinator.base_url}/state",
            body=msgpack.packb({"uptime": 99, "pwms": []}),
        )
        http.get(
            f"{coordinator.base_url}/state",
            body=msgpack.packb({**FAKE_STATE, "uptime": 100}),
        )
        assert await coordinator._async_refresh_state() == before
        assert coordinator.data == before
        assert (await coordinator._async_refresh_state())["uptime"] == 100
    await coordinator.async_close()


async def test_1024_readback_recovers_controller_availability(
    coordinator: SunRiserCoordinator,
) -> None:
    """One channel above the command maximum must not reject all live state."""
    coordinator._consecutive_failures = coordinator._FAILURE_GRACE
    state = {
        **FAKE_STATE,
        "pwms": {"1": 262, "2": 499, "5": 1024, "9": 1024},
    }
    with aioresponses() as http:
        http.get(f"{coordinator.base_url}/state", body=msgpack.packb(state))
        http.get(f"{coordinator.base_url}/weather", body=msgpack.packb([]))
        http.post(f"{coordinator.base_url}/", body=msgpack.packb(FAKE_CONFIG))
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data is not None
    assert coordinator.data["pwms"] == state["pwms"]
    assert coordinator.data["ok"] is True
    assert coordinator._consecutive_failures == 0
    await coordinator.async_close()


async def test_invalid_config_is_not_partially_published(
    coordinator: SunRiserCoordinator,
) -> None:
    before = dict(coordinator.config)
    with aioresponses() as http:
        http.post(
            f"{coordinator.base_url}/",
            body=msgpack.packb({"name": "bad snapshot", "pwm_count": 11}),
        )
        http.post(
            f"{coordinator.base_url}/",
            body=msgpack.packb({"name": "recovered", "pwm_count": 4}),
        )
        with pytest.raises(InvalidResponse):
            await coordinator._async_refresh_config(FAKE_STATE)
        assert coordinator.config == before
        await coordinator._async_refresh_config(FAKE_STATE)
        assert coordinator.config["name"] == "recovered"
    await coordinator.async_close()


async def test_truncated_weather_keeps_snapshot_then_recovers(
    coordinator: SunRiserCoordinator,
) -> None:
    data = {"weather": [{"rainmins": 5}]}
    with aioresponses() as http:
        http.get(f"{coordinator.base_url}/weather", body=b"\x91\x81")
        http.get(f"{coordinator.base_url}/weather", body=msgpack.packb([]))
        assert (await coordinator._async_refresh_weather(dict(data))) == data
        assert (await coordinator._async_refresh_weather(dict(data)))["weather"] == []
    await coordinator.async_close()
