# Switch

One `SwitchEntity` is created per PWM channel where `pwm#X#onoff = true` and `pwm#X#color != ""`.

These channels are treated as binary (on/off) — the device still accepts a PWM value, but the controller UI presents them as switches.

## Reference

::: custom_components.sunriser.switch
