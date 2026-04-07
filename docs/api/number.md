# Number

One `NumberEntity` per active PWM channel, exposing `pwm#X#fixed` — the brightness value used when the channel manager is set to `fixed` mode.

- Range: 0–{{ cfg.pwm_max }} (device native units)
- Mode: slider
- Writing updates `pwm#X#fixed` in device config via `PUT /`

## Reference

::: custom_components.sunriser.number
