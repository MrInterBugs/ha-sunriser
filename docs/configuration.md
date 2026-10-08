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

The card displays the selected daily/weekly schedule and provides explicit Save
and Discard editing. Fixed and unassigned channels are labelled. See
[Schedule editing](#schedule-editing-firmware-1006) below for details. Its refresh
reads program details on demand without increasing the coordinator polling rate.

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

## Weather profile assignment (firmware 1.006+)

Enable the optional **Weather Profile** select for each channel in the device's
entity settings. Select an existing profile or **None**. Names include the profile
ID so identically named profiles remain distinguishable. Renaming a profile does
not change the entity identity. Changes in the vendor interface appear after a
successful poll. A missing assigned profile is shown explicitly until reassigned.

This changes only the channel assignment. Create profiles and edit their shared
cloud/rain/thunder/moon settings in the vendor interface; no storm commands are
sent when selecting a profile.

## Schedule editing (firmware 1.006+)

The existing Day Planner card now displays the daily or weekly curve selected by
each channel's planner. Fixed and unassigned channels are labelled separately.
Weekly selection uses the controller's timezone (`tz`, or its legacy UTC offset
and summertime flag), not the browser timezone. If that information is missing,
no weekly curve is guessed. Curves describe scheduled output before weather,
maintenance, manual changes, and other overrides.

- **Edit daily curve** opens a time/percentage table with a local preview. Times
  must be unique, from `00:00` through `24:00`; percentages are whole numbers from
  0 to 100. Save does not switch the channel to daily planning.
- **Edit week** assigns existing named programs to each weekday and a fallback.
  An unassigned day uses the fallback; no fallback means no program.
- **Named programs → Edit program** edits an existing shared program. The editor
  lists channels using it; saving affects every channel referencing that program.
- **Save** persists the draft; **Discard** makes no controller changes. Background
  refreshes do not replace drafts, and failed saves retain edits.

Before saving, the integration re-reads the target and rejects a changed revision.
Discard and reopen to load current values after a conflict. This detects changes
observed before the write; the firmware offers no atomic compare-and-swap against
simultaneous vendor-interface writes. If a request times out, reload the values
before retrying because the controller may have accepted it.

Program creation/deletion/renaming, graph dragging, and bulk copying are not part
of this editor. Existing day/week service actions keep their previous semantics.
The card fetches program details on demand; normal polling does not fetch the
program library. No controller writes occur until Save is pressed.
