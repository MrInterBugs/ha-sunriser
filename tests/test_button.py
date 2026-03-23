# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for SunRiser button platform (reboot)."""

from unittest.mock import AsyncMock

import pytest

from tests.conftest import ENTRY_ID
from custom_components.sunriser.button import SunRiserRebootButton


class _FakeEntry:
    entry_id = ENTRY_ID


def test_reboot_button_unique_id(coordinator):
    button = SunRiserRebootButton(coordinator, _FakeEntry())
    assert button.unique_id == f"{ENTRY_ID}_reboot"


def test_reboot_button_name(coordinator):
    button = SunRiserRebootButton(coordinator, _FakeEntry())
    assert button.name == "Reboot"


async def test_reboot_button_press_calls_coordinator(coordinator):
    coordinator.async_reboot = AsyncMock()
    button = SunRiserRebootButton(coordinator, _FakeEntry())
    await button.async_press()
    coordinator.async_reboot.assert_called_once()
