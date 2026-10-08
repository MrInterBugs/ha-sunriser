# Switch

One `SwitchEntity` is created per PWM channel where `pwm#X#onoff = true` and `pwm#X#color != ""`.

These channels are treated as binary (on/off) — the device still accepts a PWM value, but the controller UI presents them as switches.

The DST Auto-Track helper is available on firmware older than 1.006. Firmware 1.006 and newer handle DST themselves; the integration removes the old helper and stops its configuration writes, including after a firmware upgrade detected during polling.

## Reference

::: custom_components.sunriser.switch
