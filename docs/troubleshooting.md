# Troubleshooting

## Known limitations

!!! warning
    Do not use the SunRiser web interface while this integration is running. The device has limited capacity for concurrent connections, and accessing the web UI at the same time as the integration polls the device can cause the controller to crash. Recovery requires either a manual power cycle or waiting for the device's watchdog (dead man's switch) to restart it automatically.

## Cannot connect to the device

**Symptom:** Integration setup fails or the connectivity binary sensor stays `Off`.

Check that the SunRiser is on the same network as HA and is reachable. Open `http://<host>/` in a browser — you should see the device web UI. Ensure no firewall or VLAN is blocking port 80 between HA and the device.

## No entities appear after setup

**Symptom:** The device is found but no light, switch, number, or select entities are created.

This is expected — entities can take up to four minutes to appear when first adding the device (four startup requests, one per poll interval), because the integration staggers its startup requests to avoid overwhelming the SunRiser's single-connection Wi-Fi module.

If entities still don't appear after a few minutes, check that each active PWM channel has a `color` field set in the device config. An empty `color` means the channel is physically unused and the integration will not create an entity for it. Log into the SunRiser web UI, assign a colour to each active channel, and reload the integration. Channels are picked up automatically on the next coordinator poll.

## State values stop updating

**Symptom:** Entity states are stale or show as unavailable.

Check the poll interval under **Settings → Devices & Services → SunRiser → Configure** — a very long interval means infrequent updates. Confirm nothing is blocking HTTP between HA and the device. Avoid using the SunRiser web UI simultaneously with the integration (see [Known limitations](#known-limitations) above).

## Light brightness reverts after ~60 seconds

**Symptom:** Setting a light to a specific brightness from HA works, but then it changes back on its own.

This is expected device behaviour. A direct PWM write from HA overrides the running program for approximately one minute, after which the device's own dayplanner or weekplanner schedule resumes. To keep manual control permanently, use the **Manager** select entity for that channel and set it to `none`.
