# SPDX-License-Identifier: GPL-3.0-or-later
"""Failure classification, log transitions, and independent read freshness."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant.helpers import issue_registry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.responses import InvalidResponse
from tests.conftest import FAKE_STATE


@pytest.mark.parametrize("source", ["state", "weather", "config"])
async def test_unexpected_errors_reach_ha_with_traceback(
    coordinator: SunRiserCoordinator, caplog: pytest.LogCaptureFixture, source: str
) -> None:
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(return_value={})
    error = RuntimeError("implementation bug")
    setattr(coordinator, f"async_get_{source}", AsyncMock(side_effect=error))
    with caplog.at_level(logging.ERROR):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.last_exception is error
    assert any(
        record.exc_info and record.exc_info[1] is error for record in caplog.records
    )
    assert coordinator._consecutive_failures == 0
    assert coordinator._auxiliary_failures == {"weather": 0, "configuration": 0}
    assert not issue_registry.async_get(coordinator.hass).issues


@pytest.mark.parametrize("source", ["weather", "configuration"])
@pytest.mark.parametrize(
    "error",
    [TimeoutError(), aiohttp.ClientConnectionError(), InvalidResponse("bad field")],
)
async def test_auxiliary_outage_warns_once_and_recovers(
    coordinator: SunRiserCoordinator,
    caplog: pytest.LogCaptureFixture,
    source: str,
    error: Exception,
) -> None:
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[{"rainmins": 2}])
    coordinator.async_get_config = AsyncMock(return_value={"name": "original"})
    with patch(
        "custom_components.sunriser.coordinator.dt_util.utcnow", return_value=now
    ):
        await coordinator.async_refresh()
    before = dict(coordinator._last_successful_read)
    method = "async_get_config" if source == "configuration" else "async_get_weather"
    result: dict[str, str] | list[object] = (
        {"name": "recovered"} if source == "configuration" else []
    )
    setattr(coordinator, method, AsyncMock(side_effect=error))
    later = now + timedelta(minutes=5)
    with caplog.at_level(logging.INFO), patch(
        "custom_components.sunriser.coordinator.dt_util.utcnow", return_value=later
    ):
        for _ in range(5):
            await coordinator.async_refresh()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1 and f"{source} read failed 3" in warnings[0].message
        assert coordinator.last_update_success
        assert coordinator._last_successful_read[source] == before[source]
        assert coordinator._last_successful_read["state"] == later
        other = "weather" if source == "configuration" else "configuration"
        assert coordinator._last_successful_read[other] == later
        if source == "configuration":
            assert coordinator.config["name"] == "original"
        else:
            assert (coordinator.data or {})["weather"] == [{"rainmins": 2}]
        setattr(coordinator, method, AsyncMock(return_value=result))
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert coordinator._last_successful_read[source] == later
        assert coordinator._auxiliary_failures[source] == 0
        assert (
            sum(f"{source} reads recovered" in r.message for r in caplog.records) == 1
        )
        # A new outage gets its own warning after the same threshold.
        setattr(coordinator, method, AsyncMock(side_effect=error))
        for _ in range(3):
            await coordinator.async_refresh()
        assert sum(r.levelno == logging.WARNING for r in caplog.records) == 2


async def test_failed_state_does_not_advance_any_read_timestamp(
    coordinator: SunRiserCoordinator,
) -> None:
    coordinator.async_get_state = AsyncMock(return_value=FAKE_STATE)
    coordinator.async_get_weather = AsyncMock(return_value=[])
    coordinator.async_get_config = AsyncMock(return_value={})
    await coordinator.async_refresh()
    before = dict(coordinator._last_successful_read)
    coordinator.async_get_state = AsyncMock(side_effect=TimeoutError())
    await coordinator.async_refresh()
    assert coordinator._last_successful_read == before
    assert not coordinator._last_state_refresh_succeeded
    assert coordinator.last_update_success  # Existing grace period is retained.
