"""Shared concrete types for integration test fixtures."""

from collections.abc import Iterable
from unittest.mock import AsyncMock

from homeassistant.core import ServiceResponse
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sunriser.coordinator import SunRiserCoordinator

type Controllers = list[tuple[MockConfigEntry, SunRiserCoordinator, DeviceEntry]]


def collect_entities(target: list[Entity]) -> AddEntitiesCallback:
    """Capture platform entities using Home Assistant's callback signature."""

    def add(new_entities: Iterable[Entity], update_before_add: bool = False) -> None:
        target.extend(new_entities)

    return add


def as_async_mock(method: object) -> AsyncMock:
    """Verify a patched method before inspecting its mock calls."""
    assert isinstance(method, AsyncMock)
    return method


def require_value[T](value: T | None) -> T:
    """Assert a test precondition and narrow an optional value."""
    assert value is not None
    return value


def response_path(response: ServiceResponse) -> str:
    """Assert that a file-export service returned its documented path."""
    assert response is not None
    path = response["path"]
    assert isinstance(path, str)
    return path
