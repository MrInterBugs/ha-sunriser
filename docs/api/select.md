# Select

One `SelectEntity` per active PWM channel, exposing `pwm#X#manager` — the scheduling mode for that channel.

## Options

| Option | Device value | Description |
|---|---|---|
| `none` | `0` | No automatic program; channel is manual |
| `dayplanner` | `1` | Uses the day-planner schedule |
| `weekplanner` | `2` | Uses the week-planner schedule |
| `fixed` | `3` | Holds the value set in `pwm#X#fixed` |

## Reference

::: custom_components.sunriser.select
