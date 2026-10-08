# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for dynamic-devices and stale-devices rules.

Each platform must:
- Add entities when a PWM channel becomes active (color goes from "" to non-empty).
- Remove entities from the entity registry when a channel is deactivated (color -> "").

The listener callback is captured from coordinator.async_add_listener so it can be
triggered directly without needing a full HA event loop integration setup.
"""

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator
from custom_components.sunriser.light import async_setup_entry as light_setup
from custom_components.sunriser.number import async_setup_entry as number_setup
from custom_components.sunriser.select import async_setup_entry as select_setup
from custom_components.sunriser.sensor import async_setup_entry as sensor_setup
from custom_components.sunriser.switch import async_setup_entry as switch_setup
from tests.conftest import DOMAIN, ENTRY_ID, FAKE_STATE
from tests.typing import collect_entities

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_listener(
    coordinator: SunRiserCoordinator,
) -> list[Callable[[], None] | None]:
    """Patch async_add_listener to capture the last registered callback.

    Returns a list; the first element is updated in place to hold the callback.
    """
    captured: list[Callable[[], None] | None] = [None]

    def _fake_add_listener(
        update_callback: Callable[[], None], context: Any = None
    ) -> Callable[[], None]:
        captured[0] = update_callback
        return lambda: None  # unsubscribe no-op

    coordinator.async_add_listener = _fake_add_listener
    return captured


def _add_entity_to_registry(
    hass: HomeAssistant,
    platform: str,
    domain: str,
    unique_id: str,
    config_entry: MockConfigEntry,
) -> entity_registry.RegistryEntry:
    """Pre-populate the entity registry so removal can be verified.

    MockConfigEntry must be registered with HA before the entity registry
    will accept a link to it.
    """
    config_entry.add_to_hass(hass)
    er = entity_registry.async_get(hass)
    return er.async_get_or_create(
        platform, domain, unique_id, config_entry=config_entry
    )


# ---------------------------------------------------------------------------
# light.py
# ---------------------------------------------------------------------------


async def test_light_dynamic_add_when_channel_becomes_active(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Channel 3 starts unused; activating it (setting color) adds a light entity."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await light_setup(hass, mock_config_entry, collect_entities(added))
    assert len(added) == 2  # ch1 (4500k dimmable) + ch4 (6500k dimmable)
    assert captured[0] is not None

    # Activate channel 3 as a dimmable light.
    coordinator.config["pwm#3#color"] = "6500k"
    coordinator.config["pwm#3#onoff"] = False

    assert captured[0] is not None
    captured[0]()  # fire the listener

    assert len(added) == 3
    uids = {e.unique_id for e in added}
    assert f"{ENTRY_ID}_pwm_3" in uids


async def test_light_stale_entity_removed_when_channel_deactivated(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Deactivating channel 1 (color -> '') removes it from the entity registry."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await light_setup(hass, mock_config_entry, collect_entities(added))
    assert len(added) == 2

    # Pre-register the entity so the registry has it.
    _add_entity_to_registry(
        hass, "light", DOMAIN, f"{ENTRY_ID}_pwm_1", mock_config_entry
    )
    er = entity_registry.async_get(hass)
    assert er.async_get_entity_id("light", DOMAIN, f"{ENTRY_ID}_pwm_1") is not None

    # Deactivate channel 1.
    coordinator.config["pwm#1#color"] = ""

    assert captured[0] is not None
    captured[0]()  # fire the listener

    assert er.async_get_entity_id("light", DOMAIN, f"{ENTRY_ID}_pwm_1") is None


async def test_light_no_duplicate_on_repeated_listener_calls(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Firing the listener repeatedly for an already-active channel adds no duplicates."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await light_setup(hass, mock_config_entry, collect_entities(added))
    initial_count = len(added)

    assert captured[0] is not None
    captured[0]()
    assert captured[0] is not None
    captured[0]()

    assert len(added) == initial_count


# ---------------------------------------------------------------------------
# switch.py
# ---------------------------------------------------------------------------


async def test_switch_dynamic_add_when_channel_becomes_active(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Channel 3 starts unused; activating it as an on/off channel adds a switch."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await switch_setup(hass, mock_config_entry, collect_entities(added))
    # Maintenance + timelapse + DST auto + pwm2 (pump, onoff=True)
    assert len(added) == 4

    # Activate channel 3 as an on/off switch.
    coordinator.config["pwm#3#color"] = "pump"
    coordinator.config["pwm#3#onoff"] = True

    assert captured[0] is not None
    captured[0]()

    assert len(added) == 5
    from custom_components.sunriser.switch import SunRiserSwitch

    new_switches = [e for e in added if isinstance(e, SunRiserSwitch)]
    assert any(e._pwm_num == 3 for e in new_switches)


async def test_switch_stale_entity_removed_when_channel_deactivated(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Deactivating channel 2 (color -> '') removes its switch from the registry."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await switch_setup(hass, mock_config_entry, collect_entities(added))

    _add_entity_to_registry(
        hass, "switch", DOMAIN, f"{ENTRY_ID}_pwm_2", mock_config_entry
    )
    er = entity_registry.async_get(hass)
    assert er.async_get_entity_id("switch", DOMAIN, f"{ENTRY_ID}_pwm_2") is not None

    coordinator.config["pwm#2#color"] = ""

    assert captured[0] is not None
    captured[0]()

    assert er.async_get_entity_id("switch", DOMAIN, f"{ENTRY_ID}_pwm_2") is None


# ---------------------------------------------------------------------------
# number.py
# ---------------------------------------------------------------------------


async def test_number_dynamic_add_when_channel_becomes_active(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Activating channel 3 (any color) adds a number entity for it."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await number_setup(hass, mock_config_entry, collect_entities(added))
    # ch1, ch2, ch4 active; ch3 unused
    assert len(added) == 3

    coordinator.config["pwm#3#color"] = "6500k"

    assert captured[0] is not None
    captured[0]()

    assert len(added) == 4
    uids = {e.unique_id for e in added}
    assert f"{ENTRY_ID}_pwm_3_fixed" in uids


async def test_number_stale_entity_removed_when_channel_deactivated(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Deactivating channel 1 removes its number entity from the registry."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await number_setup(hass, mock_config_entry, collect_entities(added))

    _add_entity_to_registry(
        hass, "number", DOMAIN, f"{ENTRY_ID}_pwm_1_fixed", mock_config_entry
    )
    er = entity_registry.async_get(hass)
    assert (
        er.async_get_entity_id("number", DOMAIN, f"{ENTRY_ID}_pwm_1_fixed") is not None
    )

    coordinator.config["pwm#1#color"] = ""

    assert captured[0] is not None
    captured[0]()

    assert er.async_get_entity_id("number", DOMAIN, f"{ENTRY_ID}_pwm_1_fixed") is None


# ---------------------------------------------------------------------------
# select.py
# ---------------------------------------------------------------------------


async def test_select_dynamic_add_when_channel_becomes_active(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Activating channel 3 adds a manager select entity for it."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await select_setup(hass, mock_config_entry, collect_entities(added))
    assert len(added) == 3  # ch1, ch2, ch4

    coordinator.config["pwm#3#color"] = "6500k"

    assert captured[0] is not None
    captured[0]()

    assert len(added) == 4
    uids = {e.unique_id for e in added}
    assert f"{ENTRY_ID}_pwm_3_manager" in uids


async def test_select_stale_entity_removed_when_channel_deactivated(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Deactivating channel 4 removes its select entity from the registry."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await select_setup(hass, mock_config_entry, collect_entities(added))

    _add_entity_to_registry(
        hass, "select", DOMAIN, f"{ENTRY_ID}_pwm_4_manager", mock_config_entry
    )
    er = entity_registry.async_get(hass)
    assert (
        er.async_get_entity_id("select", DOMAIN, f"{ENTRY_ID}_pwm_4_manager")
        is not None
    )

    coordinator.config["pwm#4#color"] = ""

    assert captured[0] is not None
    captured[0]()

    assert er.async_get_entity_id("select", DOMAIN, f"{ENTRY_ID}_pwm_4_manager") is None


# ---------------------------------------------------------------------------
# sensor.py — DS1820 dynamic discovery
# ---------------------------------------------------------------------------


async def test_sensor_dynamic_add_new_ds1820_rom(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A DS1820 ROM appearing in state after setup triggers a new temperature entity."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await sensor_setup(hass, mock_config_entry, collect_entities(added))

    # One temperature sensor from FAKE_STATE/FAKE_CONFIG
    from custom_components.sunriser.sensor import SunRiserTemperatureSensor

    initial_temp_count = sum(isinstance(e, SunRiserTemperatureSensor) for e in added)
    assert initial_temp_count == 1

    # Simulate a new DS1820 appearing in /state and its config being fetched.
    new_rom = "112233445566"
    coordinator.data = {
        **FAKE_STATE,
        "sensors": {
            **FAKE_STATE["sensors"],
            new_rom: [1, 245],  # device_type=1 (DS1820), raw=245
        },
    }
    coordinator.config[f"sensors#sensor#{new_rom}#name"] = "Sump Temp"
    coordinator.config[f"sensors#sensor#{new_rom}#unit"] = 1
    coordinator.config[f"sensors#sensor#{new_rom}#unitcomma"] = 1

    assert captured[0] is not None
    captured[0]()

    new_temp_count = sum(isinstance(e, SunRiserTemperatureSensor) for e in added)
    assert new_temp_count == 2
    new_entity = next(
        e
        for e in added
        if isinstance(e, SunRiserTemperatureSensor) and e._rom == new_rom
    )
    assert new_entity.unique_id == f"{ENTRY_ID}_sensor_{new_rom}"


async def test_sensor_no_duplicate_ds1820_on_repeated_updates(
    hass: HomeAssistant,
    coordinator: SunRiserCoordinator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same DS1820 ROM must not create duplicate entities across polls."""
    mock_config_entry.runtime_data = coordinator
    captured = _capture_listener(coordinator)

    added: list[Entity] = []
    await sensor_setup(hass, mock_config_entry, collect_entities(added))

    from custom_components.sunriser.sensor import SunRiserTemperatureSensor

    initial_count = sum(isinstance(e, SunRiserTemperatureSensor) for e in added)

    # Fire listener multiple times without new ROMs.
    assert captured[0] is not None
    captured[0]()
    assert captured[0] is not None
    captured[0]()

    assert sum(isinstance(e, SunRiserTemperatureSensor) for e in added) == initial_count
