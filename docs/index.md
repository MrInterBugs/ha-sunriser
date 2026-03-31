# SunRiser HA Integration

A community-made Home Assistant custom integration for the **SunRiser 8/10** LED aquarium controller by [LEDaquaristik.de](https://ledaquaristik.de).

This integration was reverse-engineered from the [open-source SunRiser firmware](https://github.com/LEDaquaristik/sunriser) and built by the community. It is not affiliated with or supported by LEDaquaristik.

## What it does

Connects HA to a SunRiser controller over HTTP using the [MessagePack](https://msgpack.org/) binary protocol. Each active PWM channel gets one or more entities depending on its role, and there are service actions for backup, restore, scheduling, and diagnostics.

## Entity types

| Platform | Created when |
|---|---|
| `light` | PWM channel with `pwm#X#onoff = false` (dimmable light) |
| `switch` | PWM channel with `pwm#X#onoff = true` (on/off only) |
| `select` | Every active channel — controls the manager (none / dayplanner / weekplanner / fixed) |
| `number` | Every active channel — sets the fixed brightness (0–1000) |
| `sensor` | Uptime, firmware version, hostname, DS1820 temperature probes, weather state |
| `binary_sensor` | Device connectivity (derived from last poll result) |
| `button` | Reboot |

Channels where `pwm#X#color` is empty are unused and produce no entities.

## Key facts

- Protocol: MessagePack over HTTP/1.1 (no HTTP/2)
- Config keys use `#` as separator, e.g. `pwm#1#color`
- PWM range: 0–1000 (mapped to HA brightness 0–255)
- Direct state writes hold for ~1 minute before the device's own program resumes
- Polling is staggered: `state → weather → pwm_config`, one HTTP request per tick — needed because the WizFi360 Wi-Fi module can only handle one connection at a time

## Installation

Install via [HACS](https://hacs.xyz/) by adding this repository as a custom integration. See the [README](https://github.com/MrInterBugs/ha-sunriser#installation-via-hacs) for step-by-step instructions.

## Links

- [GitHub repository](https://github.com/MrInterBugs/ha-sunriser)
- [Report an issue](https://github.com/MrInterBugs/ha-sunriser/issues)
- [API Reference](api/index.md)
