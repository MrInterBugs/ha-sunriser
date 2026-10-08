# Sensor

Several sensor types are created at startup and dynamically as new data appears.

## Diagnostic sensors (static)

| Entity | Source key | Notes |
|---|---|---|
| Uptime | `state.uptime` | Seconds since last boot |
| Firmware Version | `config.factory_version` | Running firmware; refreshed with periodic configuration reads |
| Hostname | `config.hostname` | Device hostname |

These use `EntityCategory.DIAGNOSTIC`.

## DS1820 temperature sensors (dynamic)

One sensor per ROM address found in `GET /state → sensors`. New probes are added without a reload once their names, units, and decimal scaling have been loaded.

- Name comes from `sensors#sensor#{rom}#name`
- Unit: `sensors#sensor#{rom}#unit` (0 = raw, 1 = °C). Raw readings have no HA unit or temperature device class; Celsius readings use both.
- Decimal places: `sensors#sensor#{rom}#unitcomma`

## Weather simulation sensors (dynamic)

One sensor per channel present in the weather response. Its state is `thunder`, `rain`, `cloudy`, `moon`, or `clear`, in that precedence order. Attributes include the weather program name, activity flags, and timing details; future event ticks are converted to timestamps.

## Reference

::: custom_components.sunriser.sensor
