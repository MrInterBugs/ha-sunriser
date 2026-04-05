# Configuration

## Initial setup parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| Host | IP address or hostname of the SunRiser device | — |
| Port | HTTP port the device listens on | `80` |

## Options

After setup, go to **Settings → Devices & Services → SunRiser → Configure** to adjust:

| Option | Description | Range / Format | Default |
|--------|-------------|----------------|---------|
| Poll interval | How often HA fetches the device state | 5–3600 s | 60 s |
| Scheduled daily reboot | Automatically reboot the controller once a day to prevent firmware instability | on / off | on |
| Scheduled reboot time | Time of day to reboot (24-hour format) | HH:MM | 04:00 |

Changing any option reloads the integration automatically — no restart required.

## How polling works

Polling is staggered: one HTTP request per tick, cycling through `state → weather → pwm_config`. This is required because the SunRiser's WizFi360 Wi-Fi module can only handle one connection at a time. PWM config is re-read every ~4 hours; new temperature sensors are picked up automatically on the next poll with no reload required.

## Entity types

| Platform | Created when |
|---|---|
| `light` | PWM channel with `pwm#X#onoff = false` (dimmable) |
| `switch` | PWM channel with `pwm#X#onoff = true` (on/off only), plus Maintenance Mode |
| `select` | Every active channel — controls the manager (`none` / `dayplanner` / `weekplanner` / `fixed`) |
| `number` | Every active channel — sets the fixed brightness (0–1000) |
| `sensor` | Uptime, firmware version, hostname, DS1820 temperature probes, weather state per channel |
| `binary_sensor` | Device connectivity (derived from last poll result) |
| `button` | Reboot |

Channels where `pwm#X#color` is empty are unused and produce no entities. To activate a channel, log into the SunRiser web UI and assign a colour to it — the integration will pick it up automatically on the next poll.
