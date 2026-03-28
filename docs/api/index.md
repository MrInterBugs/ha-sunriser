# API Reference

This section documents the public Python API of the `custom_components.sunriser` package.

## Modules

| Module | Purpose |
|---|---|
| [coordinator](coordinator.md) | `SunRiserCoordinator` — polls the device, holds config, exposes helper methods |
| [config_flow](config_flow.md) | UI config flow and options flow |
| [const](const.md) | Domain constants, `COLOR_NAMES`, `MANAGER_OPTIONS`, `PWM_MAX` |
| [light](light.md) | `LightEntity` per dimmable PWM channel |
| [switch](switch.md) | `SwitchEntity` per on/off PWM channel |
| [sensor](sensor.md) | Diagnostic sensors, DS1820 temperature, weather state |
| [binary_sensor](binary_sensor.md) | Device connectivity sensor |
| [button](button.md) | Reboot button |
| [number](number.md) | Fixed-brightness number entity per channel |
| [select](select.md) | Manager-mode select entity per channel |
| [diagnostics](diagnostics.md) | `async_get_config_entry_diagnostics` implementation |
| [init](init.md) | Integration setup, service registration |

## Protocol overview

```
POST /          msgpack([key, ...])       → msgpack({key: value, ...})   # read config
PUT  /          msgpack({key: value, ...}) → 204                          # write config
GET  /state     →  msgpack({pwms, sensors, uptime, ...})                  # live state
PUT  /state     msgpack({pwms: {...}})    → 204                          # set PWM values
GET  /weather   →  msgpack stream, first object is list per channel
GET  /reboot    →  reboots device
DELETE /        →  factory reset
```

All requests use `Content-Type: application/x-msgpack` and must go over HTTP/1.1 with `Connection: close` to avoid the WizFi360 keep-alive bug.
