# SPDX-License-Identifier: GPL-3.0-or-later
"""The schema library follows the Home Assistant release."""

import importlib
import sys
from unittest.mock import patch

import pytest

from custom_components.sunriser import schema


def test_uses_probatio_when_available() -> None:
    assert schema.vol.__name__ == "probatio"


def test_falls_back_to_voluptuous_before_2026_10() -> None:
    voluptuous = pytest.importorskip("voluptuous")
    try:
        with patch.dict(sys.modules, {"probatio": None}):
            assert importlib.reload(schema).vol is voluptuous
    finally:
        importlib.reload(schema)
    assert schema.vol.__name__ == "probatio"
