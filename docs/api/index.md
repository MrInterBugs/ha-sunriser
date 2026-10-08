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
PUT  /          msgpack({key: value, ...}) → success                     # write config
GET  /state     →  msgpack({pwms, sensors, uptime, ...})                  # live state
PUT  /state     msgpack({pwms: {...}})    → success                     # set PWM values
GET  /weather   →  msgpack stream, first object is list per channel
GET  /reboot    →  reboots device
DELETE /        →  factory reset
```

MessagePack request bodies use `Content-Type: application/x-msgpack`. Write methods accept successful HTTP status codes and raise on HTTP errors. The HTTP session uses normal connection reuse.

## Firmware 1.006 maintenance contract

Verified on 2026-10-08 against the vendor's served 1.006 web client:
[page](http://srdemo.ledaquaristik.de/#service),
[bundle](http://srdemo.ledaquaristik.de/assets/sunriser-1.006.min.js?1791039269).
Bundle SHA-256: `1ebaf5af50bd345affe70bfdc29c67844132123f40740a82f908995725110965`.
The public GitHub master at `3de3e3550b5d1869630eeadeecda239f6c110dfb`
still describes the older maintenance interface; it is not the source of these
new fields. No vendor code is copied into the integration.

| Operation/field | Contract |
|---|---|
| Start/end maintenance | `PUT /state`, integer `service_mode: 1/0` |
| Start/end blackout | `PUT /state`, integer `blackout: 1/0` |
| Read modes | `GET /state`: nonzero `service_mode` means active session; `blackout` distinguishes blackout |
| Countdown | Optional `service_left`, seconds remaining; missing/nonpositive means no expiry estimate |
| Timeout | Configuration `service_timeout`, integer minutes 0–10080, default 1440; zero is indefinite |
| Dimmable level | Configuration `pwm#X#service`, integer percent 0–100 |
| On/off level | Same field, 0 or 100; absent value displayed as off by the vendor UI |
| Exclusion | Configuration `pwm#X#nomaint`, boolean, default false |
| Legacy level fallback | If dimmable channel level is unset, floor `service_value / 10`, clamped to 0–100; otherwise default 100 |

Configuration reads use the existing `POST /` key list. Writes use `PUT /` with
only changed keys and the existing `save_version` metadata. All new fields share
the normal bulk configuration poll. Existing maintenance switch identity and
session semantics are retained. New entities are firmware-gated and discovered
on polling; unknown versions do not enable writes. No additional pacing or global
request queue is introduced.

The vendor UI confirms that starting either mode can replace the other, that
excluded channels continue outside its control, and that saved settings affect
running maintenance. It describes `/factorybackup` as the previous configuration
preserved at reset, not pristine factory defaults.

Validation boundary: the public simulator's read-only state reported `service_mode: 0`
and `blackout: false`; it did not include `service_left`. Tests exercise explicit
synthetic countdown/active-mode fixtures and HTTP contracts. No real controller
was written to during protocol validation. Remaining hardware checks include mode
changes in both directions,
automatic expiry, changing timeout mid-session, excluded/on-off outputs, physical
button changes, and HA restart during a running session on firmware 1.006 hardware. These checks
were not performed against the combined v2.1.0 build.

::: custom_components.sunriser.maintenance
