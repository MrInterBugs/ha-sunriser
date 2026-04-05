# Installation

## Requirements

- Home Assistant 2024.1.0 or newer
- SunRiser 8 or 10 on your local network
- [HACS](https://hacs.xyz/) installed

## Install via HACS

1. Open HACS in your Home Assistant sidebar
2. Click the **three-dot menu** (top right) and select **Custom repositories**
3. Paste `https://github.com/MrInterBugs/ha-sunriser` into the URL field
4. Set category to **Integration** and click **Add**
5. Search for **SunRiser** in HACS and click **Download**
6. Restart Home Assistant

## Set up the integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **SunRiser**
3. Enter your device's IP address or hostname (default hostname: `sunriser`)
4. Enter the port if you changed it from the default (default: `80`)
5. Click **Submit**

The integration will automatically detect all active PWM channels and temperature sensors on your device.

!!! note
    Entities can take up to four minutes to appear after first adding the device (four separate HTTP requests, one per poll interval). This is intentional — the SunRiser's WizFi360 Wi-Fi module can only handle one connection at a time, and the integration staggers its startup requests to avoid crashing the controller.

## Automatic discovery

The integration can discover SunRiser devices automatically via DHCP. When a device with a hostname matching `sunriser*` joins your network, Home Assistant will prompt you to set it up. You can also initiate setup manually via **Settings → Devices & Services → Add Integration → SunRiser**.

## Update the host or port

If your device's IP address changes, go to **Settings → Devices & Services → SunRiser → three-dot menu → Reconfigure**. You can update the host and port without removing the integration — all automations and entity history are preserved.

## Remove the integration

1. Go to **Settings → Devices & Services**
2. Find the **SunRiser** integration and click the three-dot menu
3. Select **Delete**
4. If installed via HACS, open HACS, find **SunRiser**, and click **Remove**
5. Restart Home Assistant
