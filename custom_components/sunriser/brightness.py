# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
"""Day planner percent <-> PWM value conversion.

The day planner works in percent and dims along a fixed curve, so a planner
percent is not a linear share of the 0-1000 PWM value. Home Assistant shows
and sets brightness on the planner's percent scale.

The planner curve below was measured: for every percent, the /state readback
with a one-marker day plan at that percent, and a timed 0-12 % fade for the
lowest levels (a planner value of 1 is not visible right after a configuration
save). Measured on a SunRiser 10 with firmware 1.007. Both curves are
logarithmic and are computed below; they match the measured values at every
percent.

The controller drives one step above the planner value (any value between 0
and the channel maximum) unless the ``oldfade`` option selects the original
curve. A direct /state write is output as sent, except in fixed mode, where it
is stored as the fixed value and gets the same one step.
"""

from __future__ import annotations

import math
from bisect import bisect_right

from .const import PWM_MAX

# Planner curve: values 1 and 2 are held for shortened steps; value 2 begins
# 5 352 028 ms and value 3 begins 9 734 104 ms into a day-long (86 400 000 ms)
# fade. From value 3 the curve is logarithmic and reaches 999 at the end.
_VALUE_2_FROM = 5_352_028 / 86_400_000
_VALUE_3_FROM = 9_734_104 / 86_400_000


def _planner_value(percent: int) -> int:
    fraction = percent / 100
    if percent <= 0:
        return 0
    if percent >= 100:
        return PWM_MAX
    if fraction < _VALUE_2_FROM:
        return 1
    if fraction < _VALUE_3_FROM:
        return 2
    exponent = (fraction - _VALUE_3_FROM) / (1 - _VALUE_3_FROM)
    return math.floor(3 * math.pow(333, exponent))


# Planner value at each percent (index = percent).
PLANNER_CURVE: tuple[int, ...] = tuple(
    _planner_value(percent) for percent in range(101)
)

# The original curve (``oldfade``): each percent multiplies the value by
# 1000 ** (1 / 100), with no extra output step.
OLDFADE_CURVE: tuple[int, ...] = (
    0,
    *(math.floor(1000 ** (percent / 100)) for percent in range(1, 101)),
)


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
