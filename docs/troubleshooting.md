# Troubleshooting

## Known limitations

This experimental branch removes the request splitting, spacing, and forced connection closure previously used to work around controller instability. The assumption that firmware 1.006 resolves these limitations still needs hardware testing, including concurrent web UI use. If the controller resets or becomes unreachable, compare with the parent `fix/ha-firmware-1006` branch and record the firmware version and device logs.

## Cannot connect to the device

**Symptom:** Integration setup fails or the connectivity binary sensor stays `Off`.

Check that the SunRiser is on the same network as HA and is reachable. Open `http://<host>/` in a browser — you should see the device web UI. Ensure no firewall or VLAN is blocking port {{ cfg.default_port }} between HA and the device.

## No entities appear after setup

**Symptom:** The device is found but no light, switch, number, or select entities are created.

Entities are created as part of successful setup. Check the HA logs for failed state or configuration reads if setup is retrying. Each active PWM channel must have a `color` field set in the device configuration; an empty `color` means the channel is unused. Assign a colour in the device web UI and the integration will discover the channel on the next successful poll.

## State values stop updating

**Symptom:** Entity states are stale or show as unavailable.

Check the poll interval under **Settings → Devices & Services → SunRiser → Configure** — a very long interval means infrequent updates. Confirm nothing is blocking HTTP between HA and the device. See [Known limitations](#known-limitations) if the controller resets.

## Light brightness reverts after ~60 seconds

**Symptom:** Setting a light to a specific brightness from HA works, but then it changes back on its own.

This is expected device behaviour. A direct PWM write from HA overrides the running program for approximately one minute, after which the device's own dayplanner or weekplanner schedule resumes. To keep manual control permanently, use the **Manager** select entity for that channel and set it to `none`.
