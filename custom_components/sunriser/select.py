# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins and dynamic properties override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import planning
from .const import MANAGER_OPTIONS
from .coordinator import SunRiserCoordinator
from .discovery import pwm_entity_reconciler

PARALLEL_UPDATES = 1

_MANAGER_TO_INT: dict[str, int] = {v: k for k, v in MANAGER_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data
    check_weather = pwm_entity_reconciler(
        hass,
        entry,
        async_add_entities,
        "select",
        "_weather_profile",
        lambda channel: coordinator.supports_maintenance_config
        and "weather#web" in coordinator.config
        and not coordinator.pwm_is_unused(channel),
        lambda channel: SunRiserWeatherProfileSelect(coordinator, entry, channel),
    )
    check_weather()
    entry.async_on_unload(coordinator.async_add_listener(check_weather))
    _check_entities = pwm_entity_reconciler(
        hass,
        entry,
        async_add_entities,
        "select",
        "_manager",
        lambda channel: not coordinator.pwm_is_unused(channel),
        lambda channel: SunRiserPWMManagerSelect(coordinator, entry, channel),
    )

    _check_entities()
    entry.async_on_unload(coordinator.async_add_listener(_check_entities))


class SunRiserPWMManagerSelect(CoordinatorEntity[SunRiserCoordinator], SelectEntity):
    """Select which planner controls a PWM channel (pwm#X#manager)."""

    _attr_has_entity_name = True
    _attr_translation_key = "pwm_manager"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(MANAGER_OPTIONS.values())
    # Advanced config — most users set once and never revisit; disabled by default.
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: SunRiserCoordinator,
        entry: ConfigEntry,
        pwm_num: int,
    ) -> None:
        super().__init__(coordinator)
        self._pwm_num = pwm_num
        self._attr_unique_id = f"{entry.entry_id}_pwm_{pwm_num}_manager"
        self._attr_translation_placeholders = {"channel": coordinator.pwm_name(pwm_num)}
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str:
        return MANAGER_OPTIONS.get(self.coordinator.pwm_manager(self._pwm_num), "none")

    async def async_select_option(self, option: str) -> None:
        value = _MANAGER_TO_INT.get(option, 0)
        await self.coordinator.async_set_config({f"pwm#{self._pwm_num}#manager": value})


class SunRiserWeatherProfileSelect(
    CoordinatorEntity[SunRiserCoordinator], SelectEntity
):
    """Assign existing weather profiles without editing shared effect settings."""

    _attr_has_entity_name = True
    _attr_translation_key = "weather_profile"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: SunRiserCoordinator, entry: ConfigEntry, channel: int
    ) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_unique_id = f"{entry.entry_id}_pwm_{channel}_weather_profile"
        self._attr_translation_placeholders = {"channel": coordinator.pwm_name(channel)}
        self._attr_device_info = coordinator.device_info

    def _profiles(self) -> dict[str, int]:
        return {
            "None": 0,
            **{
                f"{p['name']} [{p['id']}]": p["id"]
                for p in planning.profiles(self.coordinator.config.get("weather#web"))
            },
        }

    @property
    def options(self) -> list[str]:
        options = list(self._profiles())
        current = self.current_option
        return options if current in options else [*options, current]

    @property
    def current_option(self) -> str:
        assigned = self.coordinator.config.get(f"pwm#{self._channel}#weather") or 0
        return next(
            (name for name, pid in self._profiles().items() if pid == assigned),
            f"Unknown profile [{assigned}]",
        )

    async def async_select_option(self, option: str) -> None:
        from homeassistant.exceptions import HomeAssistantError

        profile_id = self._profiles().get(option)
        if profile_id is None:
            raise HomeAssistantError("Select an existing weather profile")
        await self.coordinator.async_set_weather_profile(self._channel, profile_id)
