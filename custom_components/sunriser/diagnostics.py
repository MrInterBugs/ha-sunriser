# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import SunRiserCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: SunRiserCoordinator = entry.runtime_data
    return {
        "config_entry": dict(entry.data),
        "coordinator_config": coordinator.config,
        "coordinator_state": coordinator.data,
        "last_update_success": coordinator.last_update_success,
    }
