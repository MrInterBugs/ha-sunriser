# Config Flow

UI-driven setup and options flow.

## Setup parameters

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | — | IP address or hostname of the SunRiser |
| `port` | int | `80` | HTTP port |

The flow tests connectivity before completing — raises an error if the device is unreachable.

## Options parameters

| Field | Type | Default | Range / Format | Description |
|---|---|---|---|---|
| `scan_interval` | int | `60` | 5–3600 | Poll interval in seconds |
| `scheduled_reboot` | bool | `true` | — | Enable a daily automatic reboot |
| `reboot_time` | string | `04:00` | HH:MM | Time of day to reboot the controller |

Changing options triggers a full config entry reload.

Validation: `reboot_time` must be a valid 24-hour `HH:MM` string (e.g. `04:00`). An `invalid_time` error is shown in the form if the value cannot be parsed.

## Reference

::: custom_components.sunriser.config_flow
