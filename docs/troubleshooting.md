# Troubleshooting

## Cannot connect to the device

**Symptom:** Integration setup fails or the connectivity binary sensor stays `Off`.

Check that the SunRiser is on the same network as HA and is reachable from HA. Open `http://<host>:<port>/` in a browser — you should see the device web UI. Ensure no firewall or VLAN is blocking the configured HTTP port (default {{ cfg.default_port }}) between HA and the device.

## No entities appear after setup

**Symptom:** The device is found but no light, switch, number, or select entities are created.

Entities are created as part of successful setup. Check the HA logs for failed state or configuration reads if setup is retrying. Each active PWM channel must have a `color` field set in the device configuration; an empty `color` means the channel is unused. Assign a colour in the device web UI and the integration will discover the channel on the next successful poll.

## State values stop updating

**Symptom:** Entity states are stale or show as unavailable.

Check the poll interval under **Settings → Devices & Services → SunRiser → Configure** — a very long interval means infrequent updates. Confirm nothing is blocking HTTP between HA and the device. The connectivity sensor turns off after the first failed state poll. Other entities retain their last values until {{ cfg.failure_grace }} consecutive state failures make the controller unavailable. A successful state poll restores availability and clears the repair notification.

State, configuration, and weather reads can fail independently. After three
consecutive weather or configuration failures, the integration logs one warning
and retains the previous values. It logs recovery after a successful read; a
successful state read alone does not mean configuration or weather is fresh.
These failures do not change the existing state-read availability grace period.
Unexpected programming errors are logged by Home Assistant with a traceback,
rather than being classified as a controller connection failure.

If resets persist, include the integration version, controller firmware version, poll interval, and relevant HA/controller logs in an issue.

## Light brightness reverts after ~60 seconds

**Symptom:** Setting a light to a specific brightness from HA works, but then it changes back on its own.

This is expected device behaviour. A direct PWM write from HA overrides the running program for approximately one minute, after which the device's own dayplanner or weekplanner schedule resumes. For persistent output, enable the channel's **Manager** select and **Fixed Value** number in its entity settings. Set Manager to `fixed` and choose a Fixed Value between 0 and {{ cfg.pwm_max }}. Switch back to `dayplanner` or `weekplanner` to resume a schedule.

## Icon missing only in HACS

Home Assistant 2026.3 and later can load the bundled SunRiser icon from the integration's `brand/` directory. HACS versions affected by [issue #5171](https://github.com/hacs/integration/issues/5171) use an external image service, so the HACS listing can show “icon not available” even when the icon appears correctly in HA. Check that issue for the HACS fix; this does not affect controller operation.

See Home Assistant's [local brand-image documentation](https://developers.home-assistant.io/docs/core/integration/brand_images/) for version support.

## Day Planner card is missing or empty

If the card type is missing after installation or an update, reload the dashboard page. The browser must be able to reach `unpkg.com`, which supplies the card's Lit dependency. Check the browser console for a failed module load if it still does not appear.

An empty chart can mean that no configured channel has an active daily or weekly curve. Check the selected planner and its markers in the controller interface. Fixed and unassigned channels have no schedule curve. Weekly channels need a program for today or a fallback, plus valid controller timezone settings. Hover over the legend for planner/program details. If multiple controllers are loaded, set the card's `device_id`; see [card configuration](configuration.md#day-planner-card).

The card is read-only. If it still shows an older layout after an update, restart Home Assistant and hard-refresh the dashboard.

## Missing manager, fixed-value, or weather-profile controls

Manager selects, Fixed Value sliders, and Weather Profile selects are disabled by default. Weather Profile selects require firmware 1.006 or newer. Open the controller's entity list, choose the relevant entity, and enable it in the entity settings.
