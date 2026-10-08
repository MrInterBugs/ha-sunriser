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
| Poll interval | How often HA refreshes state, weather, and configuration | {{ cfg.scan_interval_min }}–{{ cfg.scan_interval_max }} s | {{ cfg.default_scan_interval }} s |
| Scheduled daily reboot | Optionally reboot the controller once a day | on / off | off |
| Scheduled reboot time | Time of day to reboot (24-hour format) | HH:MM | {{ cfg.default_reboot_time }} |

Changing any option reloads the integration automatically — no restart required. Reboot times use Home Assistant's configured timezone. Existing explicit reboot settings are preserved when upgrading.

## How polling works

Each poll reads state, weather, and configuration consecutively. Channel changes, new temperature probes, firmware changes, and weather program names are refreshed every {{ cfg.default_scan_interval }} seconds by default. New temperature sensors appear only after their names, units, and decimal scaling have loaded; failed metadata reads are retried on the next poll.

The Day Planner card reads this configuration cache. Its separate display refresh interval does not change how often HA polls the controller.

## Entity types

| Platform | Created when | Notes |
|---|---|---|
| `light` | PWM channel with `pwm#X#onoff = false` (dimmable) | |
| `switch` | PWM channel with `pwm#X#onoff = true` (on/off only) | Also creates Maintenance Mode and Time-lapse; DST Auto-Track is only created for firmware older than 1.006 |
| `select` | Every active channel — controls the manager (`none` / `dayplanner` / `weekplanner` / `fixed`) | Disabled by default; enable in entity settings |
| `number` | Every active channel — sets the fixed brightness (0–{{ cfg.pwm_max }}) | Disabled by default; enable in entity settings |
| `sensor` | Uptime, Firmware Version, and Hostname are always created; probes and weather channels are discovered from device data | Uptime is disabled by default; weather states are `clear`, `cloudy`, `rain`, `thunder`, or `moon` |
| `binary_sensor` | Always — device connectivity (derived from last state poll) | |
| `button` | Always — Reboot | |

Channels where `pwm#X#color` is empty are unused and produce no entities. To activate a channel, log into the SunRiser web UI and assign a colour to it — the integration will pick it up automatically on the next poll.

## Day Planner card

The integration registers the card resource automatically. Edit a dashboard, add a **SunRiser Day Planner** card, or use a Manual card with this YAML:

```yaml
type: custom:sunriser-dayplan-card
title: Aquarium lighting
refresh_interval: 300
```

| Setting | Description | Default |
|---|---|---|
| `title` | Card heading | `Day Planner` |
| `refresh_interval` | Seconds between display refreshes; at least 1 | `300` |
| `device_id` | HA device ID of the SunRiser controller; required when more than one is loaded | The only loaded controller |
| `channels` | Map of PWM channel numbers to display labels | Controller channel names |

For multiple controllers or custom labels:

```yaml
type: custom:sunriser-dayplan-card
device_id: YOUR_HOME_ASSISTANT_DEVICE_ID
channels:
  1: White LEDs
  2: Blue LEDs
```

To find the device ID, select the controller in **Developer Tools → Actions** for a SunRiser action and switch to YAML to copy `data.device_id`.

The card shows channels with stored day-planner markers. It does not show live PWM output, weather effects, or which week-planner program is currently active. Use the light and weather entities for live values. A schedule changed in the device web UI appears after a successful controller poll and the next card refresh.
