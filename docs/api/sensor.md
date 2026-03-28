# Sensor

Several sensor types are created at startup and dynamically as new data appears.

## Diagnostic sensors (static)

| Entity | Source key | Notes |
|---|---|---|
| Uptime | `state.uptime` | Seconds since last boot |
| Firmware Version | `state.version` | String |
| Hostname | `config.hostname` | Device hostname |

These use `EntityCategory.DIAGNOSTIC`.

## DS1820 temperature sensors (dynamic)

One sensor per ROM address found in `GET /state → sensors`. New probes appearing after startup are added dynamically without a reload.

- Name comes from `sensors#sensor#{rom}#name`
- Unit: `sensors#sensor#{rom}#unit` (0 = raw, 1 = °C)
- Decimal places: `sensors#sensor#{rom}#unitcomma`

## Weather simulation sensors (dynamic)

One sensor per channel that has a weather program assigned. Reports the current `clouds_state` or similar weather simulation parameter.

## Reference

::: custom_components.sunriser.sensor
