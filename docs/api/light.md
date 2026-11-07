# Light

One `LightEntity` is created per PWM channel where `pwm#X#onoff = false` and `pwm#X#color != ""`.

## Brightness mapping

Brightness uses the day planner's percent scale: a light at 94 % in Home
Assistant is what the controller's day planner drives at 94 %. The planner
dims along a fixed curve (50 % is a PWM value of about 37 of
{{ cfg.pwm_max }}), so the percent is not a linear share of the PWM value.

- Readback is converted to the planner percent, honouring the controller's
  `oldfade` option and the channel maximum.
- Turning a light on writes the PWM value the planner would drive at that
  percent. HA `255` (100 %) writes {{ cfg.pwm_max }}.
- The raw PWM readback is available as the `raw_value` attribute.

Limits:

- Below about 32 % several planner percents share one PWM value (1-6 % are all
  the lowest step). Readback shows the highest of them, so a light set to 3 %
  reads back as 6 %.
- Weather effects (clouds, moon, thunder), a channel minimum, the "higher
  minimum" option and channels without smart dimming change the output after
  the planner curve. While one of them applies, brightness shows the light's
  actual level, not the planned percent.

## Reference

::: custom_components.sunriser.light
