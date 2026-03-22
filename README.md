# SunRiser Home Assistant Integration

A Home Assistant custom integration for the [SunRiser 8/10](https://www.ledaquaristik.de/) LED aquarium controller by LEDaquaristik.

## Features

- **Light** — Control each PWM channel as a dimmable light (brightness 0–100%)
- **Switch** — On/off control for PWM channels configured as on/off only
- **Sensor** — DS1820 temperature sensors and device uptime
- Auto-discovery of PWM channels and sensors from the device

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

## Notes

- PWM values are polled every 30 seconds
- Manually setting a PWM brightness from HA overrides the active program for approximately 1 minute, after which the device's own schedule resumes. If you want permanent manual control, disable the dayplanner/weekplanner program on the device.
- New temperature sensors that appear after initial setup require a reload of the integration to create their entities (**Settings → Devices & Services → SunRiser → Reload**)

## Links

- [SunRiser source code](https://github.com/LEDaquaristik/sunriser)
- [SunRiser API documentation](https://github.com/LEDaquaristik/sunriser/blob/master/SUNRISER8_API_DE.md)
- [Report an issue](https://github.com/MrInterBugs/ha-sunriser/issues)
