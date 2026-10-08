# Configuration

## Initial setup parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| Host | IP address or hostname of the SunRiser device | — |
| Port | HTTP port the device listens on | `{{ cfg.default_port }}` |

## Options

After setup, go to **Settings → Devices & Services → SunRiser → Configure** to adjust:

| Option | Description | Range / Format | Default |
|--------|-------------|----------------|---------|
| Poll interval | How often HA fetches the device state | {{ cfg.scan_interval_min }}–{{ cfg.scan_interval_max }} s | {{ cfg.default_scan_interval }} s |
| Scheduled daily reboot | Optionally reboot the controller once a day | on / off | off |
| Scheduled reboot time | Time of day to reboot (24-hour format) | HH:MM | {{ cfg.default_reboot_time }} |

Changing any option reloads the integration automatically — no restart required.

## How polling works

Each poll reads state, weather, and configuration consecutively. Channel changes, new temperature probes, firmware changes, and weather program names are refreshed every {{ cfg.default_scan_interval }} seconds by default. New temperature sensors appear only after their names, units, and decimal scaling have loaded; failed metadata reads are retried on the next poll.

The former request splitting and pacing workarounds have been removed on this experimental branch for firmware 1.006 testing. Controller stability and compatibility with older firmware still need hardware validation. An existing explicit daily reboot setting is preserved; an absent setting now defaults to off.

## Entity types

| Platform | Created when | Notes |
|---|---|---|
| `light` | PWM channel with `pwm#X#onoff = false` (dimmable) | |
| `switch` | PWM channel with `pwm#X#onoff = true` (on/off only) | Also creates Maintenance Mode, Time-lapse, and DST Auto-track switches |
| `select` | Every active channel — controls the manager (`none` / `dayplanner` / `weekplanner` / `fixed`) | Disabled by default; enable in entity settings |
| `number` | Every active channel — sets the fixed brightness (0–{{ cfg.pwm_max }}) | Disabled by default; enable in entity settings |
| `sensor` | Always — Uptime (disabled by default), Firmware Version, Hostname, DS1820 temperature probes, weather state per channel (`clear` / `cloudy` / `rain` / `thunder` / `moon`) | |
| `binary_sensor` | Always — device connectivity (derived from last state poll) | |
| `button` | Always — Reboot | |

Channels where `pwm#X#color` is empty are unused and produce no entities. To activate a channel, log into the SunRiser web UI and assign a colour to it — the integration will pick it up automatically on the next poll.
