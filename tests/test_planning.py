# SPDX-License-Identifier: GPL-3.0-or-later
"""Weather assignments and read-only daily/weekly schedule snapshots."""

from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import msgpack
import pytest
from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.sunriser import planning
from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.responses import InvalidResponse, decode_config
from custom_components.sunriser.select import (
    SunRiserWeatherProfileSelect,
    async_setup_entry,
)
from tests.conftest import FAKE_CONFIG
from tests.typing import collect_entities


@pytest.fixture
async def controller(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> AsyncIterator[tuple[SunRiserCoordinator, dict[str, Any]]]:
    coord = SunRiserCoordinator(hass, mock_config_entry)
    config = {
        **FAKE_CONFIG,
        "factory_version": "1.006",
        "tz": "Europe/Berlin",
        "weather#web": '[{"id":1,"name":"Clouds"},{"id":2,"name":"Clouds"}]',
        "pwm#1#weather": 1,
        "programs#web": [
            {"id": 1, "name": "Weekday"},
            {"id": 2, "name": "Weekend"},
            {"id": 3, "name": "Deleted"},
        ],
        "programs#setup#1#marker": [0, 0, 720, 80, 1440, 0],
        "programs#setup#2#marker": [720, 50],
        "programs#setup#3#deleted": True,
        "dayplanner#marker#1": [0, 0, 720, 60, 1440, 0],
        "dayplanner#marker#4": [720, 10],
        "weekplanner#programs#4": [2, 1, 1, 1, 0, 1, 2, 1],
    }
    coord.config = deepcopy(config)

    async def read(keys: list[str]) -> dict[str, Any]:
        return deepcopy({key: config.get(key) for key in keys})

    coord.async_get_config = AsyncMock(side_effect=read)
    with patch(
        "custom_components.sunriser.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 10, 8, 12, tzinfo=timezone.utc),
    ):
        yield coord, config
    await coord.async_close()


async def test_snapshot_uses_weekly_program_and_fallback(
    controller: tuple[SunRiserCoordinator, dict[str, Any]],
) -> None:
    coord, config = controller
    snapshot = await coord.async_get_planning()
    assert [c["pwm"] for c in snapshot["channels"]] == [1, 2, 4]
    weekly = snapshot["channels"][-1]
    assert snapshot["weekday"] == 4
    assert weekly["program_name"] == "Weekday"
    assert weekly["markers"][1]["percent"] == 80
    config["weekplanner#programs#4"][4] = 2
    snapshot = await coord.async_get_planning()
    assert snapshot["channels"][-1]["program_name"] == "Weekend"
    config["tz"] = "invalid"
    assert (await coord.async_get_planning())["channels"][-1]["markers"] == []
    config["tz"] = "Europe/Berlin"
    config["programs#web"] = None
    with aioresponses() as http:
        snapshot = await coord.async_get_planning()
        assert snapshot["channels"][-1]["markers"] == []
        assert snapshot["channels"][0]["markers"][1]["percent"] == 60
        assert not http.requests
    assert "programs" not in snapshot
    assert "revision" not in str(snapshot)


async def test_weather_names_identity_and_external_removal(
    controller: tuple[SunRiserCoordinator, dict[str, Any]],
    mock_config_entry: MockConfigEntry,
) -> None:
    coord, config = controller
    entity = SunRiserWeatherProfileSelect(coord, mock_config_entry, 1)
    uid = entity.unique_id
    assert entity.options == ["None", "Clouds [1]", "Clouds [2]"]
    assert entity.current_option == "Clouds [1]"
    with aioresponses() as http:
        http.put(f"{coord.base_url}/", status=200)
        await entity.async_select_option("Clouds [2]")
        payload = msgpack.unpackb(
            http.requests[("PUT", URL(f"{coord.base_url}/"))][0].kwargs["data"],
            raw=False,
        )
        assert payload == {"pwm#1#weather": 2, "save_version": "1.006"}
    assert entity.current_option == "Clouds [2]"
    coord.config["weather#web"] = [{"id": 2, "name": "Renamed"}]
    assert entity.unique_id == uid
    assert entity.current_option == "Renamed [2]"
    config["weather#web"] = None
    with pytest.raises(HomeAssistantError, match="no longer exists"):
        await entity.async_select_option("Renamed [2]")
    coord.config["weather#web"] = None
    assert entity.options == ["None", "Unknown profile [2]"]
    with pytest.raises(HomeAssistantError, match="existing"):
        await entity.async_select_option("Unknown profile [2]")
    with aioresponses() as http:
        http.put(f"{coord.base_url}/", status=200)
        await entity.async_select_option("None")
    assert entity.current_option == "None"
    config["pwm#1#color"] = ""
    with pytest.raises(HomeAssistantError, match="no longer configured"):
        await coord.async_set_weather_profile(1, 0)


async def test_weather_discovered_when_metadata_arrives(
    hass: HomeAssistant,
    controller: tuple[SunRiserCoordinator, dict[str, Any]],
    mock_config_entry: MockConfigEntry,
) -> None:
    coord, _ = controller
    mock_config_entry.runtime_data = coord
    added: list[Entity] = []
    await async_setup_entry(hass, mock_config_entry, collect_entities(added))
    assert len([e for e in added if isinstance(e, SunRiserWeatherProfileSelect)]) == 3
    coord.async_update_listeners()
    assert len([e for e in added if isinstance(e, SunRiserWeatherProfileSelect)]) == 3


@pytest.mark.parametrize(
    "bad",
    [
        "{",
        {},
        [{"id": True, "name": "X"}],
        [{"id": 1, "name": "X"}, {"id": 1, "name": "Y"}],
    ],
)
async def test_malformed_profile_metadata_rejected(bad: Any) -> None:
    with pytest.raises(InvalidResponse):
        decode_config(msgpack.packb({"weather#web": bad}))


@pytest.mark.parametrize("bad", [[0], [0, -1], [0, 20, 0, 30], [1441, 0], [0, 0.1]])
async def test_malformed_program_curve_rejected(bad: Any) -> None:
    with pytest.raises(InvalidResponse):
        decode_config(msgpack.packb({"programs#setup#1#marker": bad}))


async def test_malformed_program_deleted_flag_rejected() -> None:
    with pytest.raises(InvalidResponse):
        decode_config(msgpack.packb({"programs#setup#1#deleted": "false"}))


async def test_parsing_optional_values_and_controller_timezone() -> None:
    assert planning.profiles([None, {"id": 2, "name": "Good"}]) == [
        {"id": 2, "name": "Good"}
    ]
    assert planning.assignments(None) == [0] * 8
    with pytest.raises(InvalidResponse):
        planning.assignments([1])
    now = datetime(2026, 10, 8, 23, tzinfo=timezone.utc)
    assert planning.weekday({"tz": "Europe/Berlin"}, now) == 5
    assert planning.weekday({"gmtoff": 60, "summertime": 1}, now) == 5
    assert planning.weekday({}, now) is None
