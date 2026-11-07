# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the day planner percent <-> PWM conversion."""

import pytest

from custom_components.sunriser.brightness import (
    OLDFADE_CURVE,
    PLANNER_CURVE,
    brightness_to_percent,
    percent_to_brightness,
    percent_to_command,
    readback_to_percent,
)


def _output(percent: int, *, oldfade: bool = False) -> int:
    """What the controller drives for a planner at ``percent``."""
    value = (OLDFADE_CURVE if oldfade else PLANNER_CURVE)[percent]
    return value if oldfade or value in (0, 1000) else value + 1


def _top_of_run(percent: int, curve: tuple[int, ...]) -> int:
    return max(p for p, value in enumerate(curve) if value == curve[percent])


class TestCurves:
    @pytest.mark.parametrize(
        ("curve", "total"), [(PLANNER_CURVE, 15695), (OLDFADE_CURVE, 14914)]
    )
    def test_shape_and_checksum(self, curve: tuple[int, ...], total: int) -> None:
        assert len(curve) == 101
        assert curve[0] == 0 and curve[100] == 1000
        assert list(curve) == sorted(curve)
        assert sum(curve) == total

    def test_spot_values(self) -> None:
        assert PLANNER_CURVE[50] == 37
        assert PLANNER_CURVE[94] == 674
        assert OLDFADE_CURVE[50] == 31


class TestReadbackToPercent:
    @pytest.mark.parametrize(
        ("raw", "percent"),
        # Issue #17 readings (SunRiser 10, 1.007): planner ~95 %, ~33 %, ~4 %.
        [(675, 94), (13, 33), (2, 6)],
    )
    def test_reported_readings(self, raw: int, percent: int) -> None:
        assert readback_to_percent(raw) == percent

    @pytest.mark.parametrize("oldfade", [False, True])
    def test_every_percent_reads_back(self, oldfade: bool) -> None:
        curve = OLDFADE_CURVE if oldfade else PLANNER_CURVE
        for percent in range(101):
            raw = _output(percent, oldfade=oldfade)
            assert readback_to_percent(raw, oldfade=oldfade) == _top_of_run(
                percent, curve
            ), percent

    def test_exact_from_32_percent(self) -> None:
        for percent in range(32, 101):
            assert readback_to_percent(_output(percent)) == percent

    def test_off_and_full(self) -> None:
        assert readback_to_percent(0) == 0
        assert readback_to_percent(-1) == 0
        assert readback_to_percent(1000) == 100
        assert readback_to_percent(1024) == 100

    def test_lowest_output_is_on(self) -> None:
        assert readback_to_percent(1) == 1

    def test_channel_max_has_no_extra_step(self) -> None:
        # Capped at 500: the output stays at the cap without the extra step.
        assert readback_to_percent(500, channel_max=500) == 89
        assert readback_to_percent(500) == 89  # 499 below the full range
        assert readback_to_percent(520, channel_max=500) == 90


class TestPercentToCommand:
    def test_planner_mode_matches_planner_output(self) -> None:
        for percent in range(101):
            assert percent_to_command(percent) == _output(percent)

    def test_fixed_mode_gets_the_step_from_the_controller(self) -> None:
        for percent in range(101):
            sent = percent_to_command(percent, fixed=True)
            driven = sent + 1 if 0 < sent < 1000 else sent
            assert driven == _output(percent)

    def test_oldfade_has_no_step(self) -> None:
        for percent in range(101):
            assert percent_to_command(percent, oldfade=True) == OLDFADE_CURVE[percent]
            assert (
                percent_to_command(percent, oldfade=True, fixed=True)
                == OLDFADE_CURVE[percent]
            )

    def test_bounds(self) -> None:
        assert percent_to_command(0) == 0
        assert percent_to_command(100) == 1000
        assert percent_to_command(-5) == 0
        assert percent_to_command(120) == 1000


class TestHaBrightness:
    def test_endpoints(self) -> None:
        assert percent_to_brightness(0) == 0
        assert percent_to_brightness(100) == 255
        assert brightness_to_percent(0) == 0
        assert brightness_to_percent(255) == 100
        assert brightness_to_percent(-1) == 0
        assert brightness_to_percent(256) == 100

    def test_only_full_brightness_is_100_percent(self) -> None:
        assert brightness_to_percent(254) == 99
        assert percent_to_brightness(99) < 255

    def test_lowest_brightness_is_one_percent(self) -> None:
        assert brightness_to_percent(1) == 1
        assert percent_to_brightness(1) >= 1

    def test_every_percent_round_trips(self) -> None:
        for percent in range(101):
            assert brightness_to_percent(percent_to_brightness(percent)) == percent

    def test_monotone(self) -> None:
        values = [brightness_to_percent(b) for b in range(256)]
        assert values == sorted(values)
