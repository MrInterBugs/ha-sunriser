# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
"""Day planner percent <-> PWM value conversion.

The day planner works in percent and dims along a fixed curve, so a planner
percent is not a linear share of the 0-1000 PWM value. Home Assistant shows
and sets brightness on the planner's percent scale.

The curves below were measured: for every percent, the /state readback with a
one-marker day plan at that percent, and a timed 0-12 % fade for the lowest
levels (a planner value of 1 is not visible right after a configuration save).
Measured on a SunRiser 10 with firmware 1.007.

The controller drives one step above the planner value (any value between 0
and the channel maximum) unless the ``oldfade`` option selects the original
curve. A direct /state write is output as sent, except in fixed mode, where it
is stored as the fixed value and gets the same one step.
"""

from __future__ import annotations

from bisect import bisect_right

from .const import PWM_MAX

# Planner value at each percent (index = percent).
# fmt: off
PLANNER_CURVE: tuple[int, ...] = (
    0, 1, 1, 1, 1, 1, 1, 2, 2, 2,  # 0 %
    2, 2, 3, 3, 3, 3, 4, 4, 4, 4,  # 10 %
    5, 5, 6, 6, 6, 7, 7, 8, 8, 9,  # 20 %
    10, 10, 11, 12, 13, 14, 15, 16, 17, 18,  # 30 %
    19, 21, 22, 23, 25, 27, 29, 31, 33, 35,  # 40 %
    37, 40, 43, 46, 49, 52, 56, 59, 63, 68,  # 50 %
    72, 77, 83, 88, 94, 101, 107, 115, 122, 131,  # 60 %
    140, 149, 159, 170, 182, 194, 207, 221, 236, 252,  # 70 %
    269, 288, 307, 328, 350, 374, 399, 426, 455, 486,  # 80 %
    519, 554, 591, 631, 674, 720, 768, 820, 876, 935,  # 90 %
    1000,  # 100 %
)

# The same with the ``oldfade`` option (original fade curve, no extra step).
OLDFADE_CURVE: tuple[int, ...] = (
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1,  # 0 %
    1, 2, 2, 2, 2, 2, 3, 3, 3, 3,  # 10 %
    3, 4, 4, 4, 5, 5, 6, 6, 6, 7,  # 20 %
    7, 8, 9, 9, 10, 11, 12, 12, 13, 14,  # 30 %
    15, 16, 18, 19, 20, 22, 23, 25, 27, 29,  # 40 %
    31, 33, 36, 38, 41, 44, 47, 51, 54, 58,  # 50 %
    63, 67, 72, 77, 83, 89, 95, 102, 109, 117,  # 60 %
    125, 134, 144, 154, 165, 177, 190, 204, 218, 234,  # 70 %
    251, 269, 288, 309, 331, 354, 380, 407, 436, 467,  # 80 %
    501, 537, 575, 616, 660, 707, 758, 812, 870, 933,  # 90 %
    1000,  # 100 %
)
# fmt: on


def _curve(oldfade: bool) -> tuple[int, ...]:
    return OLDFADE_CURVE if oldfade else PLANNER_CURVE


def readback_to_percent(
    raw: int, *, oldfade: bool = False, channel_max: int = PWM_MAX
) -> int:
    """Planner percent (0-100) for a /state PWM readback.

    Below about 32 % several percents share one value; the highest of them is
    returned, as the firmware's own value-to-percent conversion does.
    """
    if raw <= 0:
        return 0
    if raw >= PWM_MAX:
        return 100
    value = raw if oldfade or raw >= channel_max else raw - 1
    return max(1, bisect_right(_curve(oldfade), value) - 1)


def percent_to_command(
    percent: int, *, oldfade: bool = False, fixed: bool = False
) -> int:
    """PWM value to write to /state so the output matches the planner at ``percent``."""
    value = _curve(oldfade)[min(100, max(0, percent))]
    if not (oldfade or fixed) and 0 < value < PWM_MAX:
        value += 1
    return value


def percent_to_brightness(percent: int) -> int:
    """HA brightness (0-255) for a planner percent."""
    if percent <= 0:
        return 0
    if percent >= 100:
        return 255
    return max(1, round(percent * 255 / 100))


def brightness_to_percent(brightness: int) -> int:
    """Planner percent for an HA brightness (0-255); only 255 is 100 %."""
    if brightness <= 0:
        return 0
    if brightness >= 255:
        return 100
    return min(99, max(1, round(brightness * 100 / 255)))
