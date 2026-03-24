# SunRiser Home Assistant Integration

A community-made Home Assistant custom integration for the [SunRiser 8/10](https://www.ledaquaristik.de/SunRiser-10-Dimmsteuerung-und-Tagessimulation-mit-WLAN/150-00) LED aquarium controller by LEDaquaristik.

## Features

- **Light** — Dimmable control (0–100%) for each PWM channel configured as a light
- **Switch** — On/off control for PWM channels configured as on/off, plus a **Maintenance Mode** switch
- **Sensor** — DS1820 temperature sensors; diagnostic sensors for Uptime, Firmware Version, and Hostname
- **Button** — **Reboot** button to restart the device directly from HA
- **Services** — Backup, restore, and log retrieval (see [Services](#services) below)
- **Options** — Configurable poll interval (5–3600 seconds, default 30s) without re-adding the integration
- Auto-discovery of PWM channels and sensors from the device
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

The integration registers four HA services under the `sunriser` domain:

| Service | Description |
|---------|-------------|
| `sunriser.backup` | Downloads all device configuration and saves it to `/config/sunriser_backup_<timestamp>.msgpack`. Returns `{"path": "..."}`. |
| `sunriser.restore` | Restores configuration from a `.msgpack` backup file. Requires `file_path` parameter. The device performs a deep restart after applying. |
| `sunriser.get_errors` | Fetches the device error log. Returns `{"content": "..."}`. |
| `sunriser.get_log` | Fetches the device diagnostic log. Returns `{"content": "..."}`. |

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
- Manually setting a PWM brightness from HA overrides the active program for approximately 1 minute, after which the device's own schedule resumes. For permanent manual control, disable the dayplanner/weekplanner on the device.
- New temperature sensors that appear after initial setup require a reload of the integration to create their entities (**Settings → Devices & Services → SunRiser → Reload**).

## Attribution

This integration was built using the [SunRiser source code](https://github.com/LEDaquaristik/sunriser) by [LEDaquaristik](https://www.ledaquaristik.de/) as reference material. The source code and configuration files from that project are licensed under the [GNU GPL v3](http://www.gnu.org/licenses/gpl-3.0). Other assets (graphics etc.) are licensed under [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/).

## Links

- [SunRiser source code](https://github.com/LEDaquaristik/sunriser)
- [SunRiser API documentation](https://github.com/LEDaquaristik/sunriser/blob/master/SUNRISER8_API_DE.md)
- [Report an issue](https://github.com/MrInterBugs/ha-sunriser/issues)
