# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the PWM ↔ HA brightness conversion functions."""

from custom_components.sunriser.light import _to_device_brightness, _to_ha_brightness


class TestToHaBrightness:
    """_to_ha_brightness(pwm_value: int) -> int"""

    def test_zero_returns_zero(self):
        assert _to_ha_brightness(0) == 0

    def test_negative_returns_zero(self):
        assert _to_ha_brightness(-1) == 0

    def test_max_returns_255(self):
        assert _to_ha_brightness(1000) == 255

    def test_above_max_returns_255(self):
        assert _to_ha_brightness(1001) == 255

    def test_midpoint_not_endpoint(self):
        """Values strictly between 0 and 1000 must map strictly between 1 and 254."""
        for pwm in [1, 100, 500, 999]:
            result = _to_ha_brightness(pwm)
            assert 1 <= result <= 254, f"pwm={pwm} → {result}"

    def test_monotone(self):
        """Higher PWM must give higher (or equal) HA brightness."""
        values = [_to_ha_brightness(i) for i in range(0, 1001, 50)]
        assert values == sorted(values)


class TestToDeviceBrightness:
    """_to_device_brightness(brightness: int) -> int"""

    def test_zero_returns_zero(self):
        assert _to_device_brightness(0) == 0

    def test_255_returns_1000(self):
        assert _to_device_brightness(255) == 1000

    def test_above_255_returns_1000(self):
        assert _to_device_brightness(256) == 1000

    def test_midpoint(self):
        result = _to_device_brightness(128)
        assert 0 < result < 1000

    def test_monotone(self):
        values = [_to_device_brightness(i) for i in range(0, 256, 16)]
        assert values == sorted(values)
