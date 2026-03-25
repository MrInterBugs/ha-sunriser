# SunRiser Home Assistant Integration

A community-made Home Assistant custom integration for the [SunRiser 8/10](https://www.ledaquaristik.de/SunRiser-10-Dimmsteuerung-und-Tagessimulation-mit-WLAN/150-00) LED aquarium controller by LEDaquaristik.

## Features

- **Light** — Dimmable control (0–100%) for each PWM channel configured as a light
- **Switch** — On/off control for PWM channels configured as on/off, plus a **Maintenance Mode** switch
- **Select** — Per-channel manager selector (`none`, `dayplanner`, `weekplanner`, `fixed`) — shows and changes which planner controls each channel
- **Sensor** — DS1820 temperature sensors; weather simulation state per channel; diagnostic sensors for Uptime, Firmware Version, and Hostname
- **Button** — **Reboot** button to restart the device directly from HA
- **Day Planner card** — built-in Lovelace card that renders all active PWM schedules as a 24-hour chart using the same LED colours as the device web UI; registered automatically, no manual setup required
- **Services** — Backup, restore, log retrieval, and dayplanner read/write (see [Services](#services) below)
- **Options** — Configurable poll interval (5–3600 seconds, default 30s) without re-adding the integration
- Auto-discovery of PWM channels and temperature sensors from the device
- "Visit device" link in the device page opens the SunRiser web UI directly from HA

## Requirements

- Home Assistant 2024.1.0 or newer
- SunRiser 8 or 10 on your local network
- [HACS](https://hacs.xyz/) installed

## Installation via HACS

1. Open HACS in your Home Assistant sidebar
2. Click the **three-dot menu** (top right) and select **Custom repositories**
3. Paste `https://github.com/MrInterBugs/ha-sunriser` into the URL field
4. Set category to **Integration** and click **Add**
5. Search for **SunRiser** in HACS and click **Download**
6. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **SunRiser**
3. Enter your device's IP address or hostname (default hostname: `sunriser`)
4. Enter the port if you changed it from the default (default: `80`)
5. Enter the password if you set one on the device (leave blank if not set)
6. Click **Submit**

The integration will automatically detect all PWM channels and temperature sensors on your device.

## Services

The integration registers the following HA services under the `sunriser` domain:

| Service | Description |
|---------|-------------|
| `sunriser.backup` | Downloads all device configuration and saves it to `/config/sunriser_backup_<timestamp>.msgpack`. Returns `{"path": "..."}`. |
| `sunriser.restore` | Restores configuration from a `.msgpack` backup file. Requires `file_path` parameter. The device performs a deep restart after applying. |
| `sunriser.get_errors` | Fetches the device error log. Returns `{"content": "..."}`. |
| `sunriser.get_log` | Fetches the device diagnostic log. Returns `{"content": "..."}`. |
| `sunriser.get_dayplanner_schedule` | Returns the day planner schedule for a PWM channel as `{"pwm": N, "name": "...", "markers": [{"time": "HH:MM", "percent": N}, ...]}`. |
| `sunriser.set_dayplanner_schedule` | Writes a new day planner schedule for a PWM channel. Accepts `pwm` and a list of `{time, percent}` markers. Changes persist across reboots. |

Example — backup and restore via automation:

```yaml
action: sunriser.backup
response_variable: result
# result.path = /config/sunriser_backup_20260323_120000.msgpack

action: sunriser.restore
data:
  file_path: /config/sunriser_backup_20260323_120000.msgpack
```

## Notes

- PWM values are polled every 30 seconds by default. Change this under **Settings → Devices & Services → SunRiser → Configure**.
- Manually setting a PWM brightness from HA overrides the active program for approximately 1 minute, after which the device's own schedule resumes. Use the Manager select entity to switch a channel to `none` for permanent manual control.
- New temperature sensors discovered after initial setup are added automatically on the next poll — no reload required.

## Attribution

This integration was built using the [SunRiser source code](https://github.com/LEDaquaristik/sunriser) by [LEDaquaristik](https://www.ledaquaristik.de/) as reference material. The source code and configuration files from that project are licensed under the [GNU GPL v3](http://www.gnu.org/licenses/gpl-3.0). Other assets (graphics etc.) are licensed under [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/).

## Links

- [SunRiser source code](https://github.com/LEDaquaristik/sunriser)
- [SunRiser API documentation](https://github.com/LEDaquaristik/sunriser/blob/master/SUNRISER8_API_DE.md)
- [Report an issue](https://github.com/MrInterBugs/ha-sunriser/issues)
