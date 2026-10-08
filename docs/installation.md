# Installation

## Requirements

- Home Assistant with HACS installed. Automated integration tests target Home Assistant 2026.2.3; an older minimum version has not been verified.
- SunRiser 8 or 10 reachable from Home Assistant on your local network
- Controller firmware 1.006 for the 2.0 release; compatibility with older firmware is unverified.

Install [HACS](https://hacs.xyz/) first if it is not already available.

## Install via HACS

1. Open HACS in your Home Assistant sidebar
2. Click the **three-dot menu** (top right) and select **Custom repositories**
3. Paste `https://github.com/MrInterBugs/ha-sunriser` into the URL field
4. Set category to **Integration** and click **Add**
5. Search for **SunRiser** in HACS and click **Download**
6. Restart Home Assistant

To test a beta, enable **Show beta versions** in the repository download dialog and select the desired prerelease.

## Set up the integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **SunRiser**
3. Enter your device's IP address or hostname (for example, `sunriser`, if it resolves on your network)
4. Enter the port if you changed it from the default (default: `{{ cfg.default_port }}`)
5. Click **Submit**

The integration will automatically detect all active PWM channels and temperature sensors on your device.

![SunRiser device page in Home Assistant](images/device_page.png)

!!! note
    Entities are created during setup after state and configuration have loaded. Home Assistant retries setup if required reads fail.

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
