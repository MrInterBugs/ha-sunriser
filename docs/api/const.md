# Constants

Shared constants used across all platform modules.

## Notable values

| Name | Value | Description |
|---|---|---|
| `DOMAIN` | `"sunriser"` | Integration domain |
| `PWM_MAX` | `1000` | Maximum PWM value on the device |
| `DEFAULT_PORT` | `80` | Default HTTP port |
| `DEFAULT_SCAN_INTERVAL` | `30` | Default poll interval (seconds) |

## `COLOR_NAMES`

Maps `pwm#X#color` IDs returned by the device to human-readable English names. Used by `SunRiserCoordinator.pwm_name()` to label entities.

Example entries: `"4500k" → "TROPIC 4500K"`, `"pump" → "Mini Pump"`.

## `MANAGER_OPTIONS`

Maps `pwm#X#manager` integer values to option labels used by the `select` entity:

| Value | Label |
|---|---|
| `0` | `none` |
| `1` | `dayplanner` |
| `2` | `weekplanner` |
| `3` | `fixed` |

## Reference

::: custom_components.sunriser.const
