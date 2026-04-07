# Light

One `LightEntity` is created per PWM channel where `pwm#X#onoff = false` and `pwm#X#color != ""`.

## Brightness mapping

PWM values (0–{{ cfg.pwm_max }}) are mapped to HA brightness (0–255) with exact endpoints:

- PWM `0` → HA `0`
- PWM `1–3` → HA `1` (avoids `is_on=True, brightness=0` contradiction)
- PWM `996–999` → HA `254`
- PWM `{{ cfg.pwm_max }}` → HA `255`

Only `HA 255` sends `PWM {{ cfg.pwm_max }}` to the device.

## Reference

::: custom_components.sunriser.light
