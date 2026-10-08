# Number

One `NumberEntity` per active PWM channel, exposing `pwm#X#fixed` — the brightness value used when the channel manager is set to `fixed` mode.

- Range: 0–{{ cfg.pwm_max }} (device native units)
- Mode: slider
- Writing updates `pwm#X#fixed` in device config via `PUT /`

Entities are disabled by default. Enable them in HA entity settings. An acknowledged write updates the displayed value immediately; a failed write preserves the old value.

## Reference

::: custom_components.sunriser.number
