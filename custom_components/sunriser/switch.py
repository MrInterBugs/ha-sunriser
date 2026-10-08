# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
# HA entity mixins and dynamic properties override cached_property descriptors.
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PWM_MAX
from .coordinator import SunRiserCoordinator
from .discovery import pwm_entity_reconciler
from .maintenance import setup_maintenance_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SunRiserCoordinator = entry.runtime_data
    setup_maintenance_entities(hass, entry, async_add_entities, "switch")
    er = entity_registry.async_get(hass)

    async_add_entities(
        [
            SunRiserMaintenanceSwitch(coordinator, entry),
            SunRiserTimelapseSwitch(coordinator, entry),
        ]
    )

    if coordinator.firmware_handles_dst:
        # Retire the old registry entry as well as suppressing its entity.
        # This prevents an orphaned, unavailable configuration switch on upgrade.
        eid = er.async_get_entity_id(
            "switch", DOMAIN, f"{entry.entry_id}_dst_auto_track"
        )
        if eid:
            er.async_remove(eid)
    else:
        async_add_entities([SunRiserDSTAutoSwitch(coordinator, entry)])

    reconcile_pwm = pwm_entity_reconciler(
        hass,
        entry,
        async_add_entities,
        "switch",
        "",
        lambda channel: coordinator.pwm_is_onoff(channel)
        and not coordinator.pwm_is_unused(channel),
        lambda channel: SunRiserSwitch(coordinator, entry, channel),
    )

    @callback
    def _check_pwm_entities() -> None:
        if coordinator.firmware_handles_dst:
            eid = er.async_get_entity_id(
                "switch", DOMAIN, f"{entry.entry_id}_dst_auto_track"
            )
            if eid:
                er.async_remove(eid)
        reconcile_pwm()

    _check_pwm_entities()
    entry.async_on_unload(coordinator.async_add_listener(_check_pwm_entities))


class SunRiserMaintenanceSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """Maintenance session switch; also on during firmware blackout (legacy semantics)."""

    _attr_has_entity_name = True
    _attr_translation_key = "maintenance_mode"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_maintenance"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        # service_mode is 0 when off, or a Unix timestamp when on
        return bool(self.coordinator.data.get("service_mode"))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_service_mode(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_service_mode(False)
        await self.coordinator.async_request_refresh()


class SunRiserSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """On/off PWM channel (pwm#X#onoff = true) on a SunRiser device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SunRiserCoordinator,
        entry: ConfigEntry,
        pwm_num: int,
    ) -> None:
        super().__init__(coordinator)
        self._pwm_num = pwm_num
        self._attr_unique_id = f"{entry.entry_id}_pwm_{pwm_num}"
        self._attr_name = coordinator.pwm_name(pwm_num)
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self.coordinator.pwm_value(self._pwm_num) > 0

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_pwms({str(self._pwm_num): PWM_MAX})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_pwms({str(self._pwm_num): 0})
        await self.coordinator.async_request_refresh()


class SunRiserTimelapseSwitch(CoordinatorEntity[SunRiserCoordinator], SwitchEntity):
    """Time-lapse (timewarp) mode — runs the day/week planner at ~1800× speed."""

    _attr_has_entity_name = True
    _attr_translation_key = "timelapse"

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_timelapse"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        return bool(self.coordinator.data.get("timewarp"))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_timewarp(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_timewarp(False)
        await self.coordinator.async_request_refresh()


class SunRiserDSTAutoSwitch(
    CoordinatorEntity[SunRiserCoordinator], SwitchEntity, RestoreEntity
):
    """Automatic DST tracking — keeps the device summertime config in sync with the HA timezone."""

    _attr_has_entity_name = True
    _attr_translation_key = "dst_auto_track"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SunRiserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dst_auto_track"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The hass.data bridge in coordinator.__init__ already restores
        # _dst_auto_track on same-session reloads (options change, reconfigure).
        # Only fall back to the recorder when the bridge didn't supply the value
        # (i.e. a true HA restart).
        if not self.coordinator.dst_auto_track:
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.state == STATE_ON:
                await self.coordinator.async_set_dst_auto_track(True)

    @property
    def is_on(self) -> bool:
        return self.coordinator.dst_auto_track

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_dst_auto_track(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_dst_auto_track(False)
        self.async_write_ha_state()
