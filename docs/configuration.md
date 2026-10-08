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

## Maintenance and blackout (firmware 1.006+)

Blackout uses the controller's own fading and timeout. Channels marked
**Maintenance Excluded** remain outside maintenance/blackout control; do not
assume that blackout switches every output off.

| Entity | Purpose |
|---|---|
| Blackout Mode switch | Start/end blackout |
| Existing Maintenance Mode switch | Start/end a maintenance session; remains **on during blackout** for compatibility |
| Operating Mode sensor | Distinguishes normal, maintenance, blackout and time-lapse; missing state is unknown |
| Maintenance Ends At sensor | Disabled by default; estimated expiry from the latest firmware countdown; unknown when inactive, indefinite, or not reported |
| Maintenance Timeout number | Persistent timeout for both modes, 0–10,080 minutes; **0 means never** |
| Per-channel Maintenance Level number | Dimmable channel's configured maintenance percentage, 0–100 |
| Per-channel Maintenance Output switch | On/off channel's configured maintenance state, not its immediate output |
| Per-channel Maintenance Excluded switch | Leave this channel outside maintenance/blackout control |

Configuration numbers, configuration switches, and Maintenance Ends At are disabled
by default. Enable them in the controller's entity settings. Existing enabled
end-time sensors retain their setting after an update; disable yours there if unwanted.
Channel controls appear only for configured channels, with a level number for
dimmable channels and an output switch for on/off channels.
Changing exclusions or levels preserves other settings and does not start a
session; firmware may apply saved changes to an already running session.
The timeout defaults to 1,440 minutes (24 hours). It is persistent configuration,
not a duration for one invocation. Turn Maintenance Mode off to end either
maintenance or blackout; no separate resume control is needed.

The controller owns expiration and output fades; these continue while HA is
stopped. HA reads state after commands and during normal polling, including
changes from the physical button. It never replays mode commands after restart.
If a command times out, its outcome can be uncertain: check state before retrying.
The estimated end time is anchored to a successful state read and is not moved
forward by failed polls. Exact timing and timeout changes during a session need
hardware beta validation.
