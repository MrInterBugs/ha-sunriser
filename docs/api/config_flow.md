# Config Flow

UI-driven setup and options flow.

## Setup parameters

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | — | IP address or hostname of the SunRiser |
| `port` | int | `{{ cfg.default_port }}` | HTTP port |

The flow tests connectivity before completing — raises an error if the device is unreachable.

## Options parameters

| Field | Type | Default | Range / Format | Description |
|---|---|---|---|---|
| `scan_interval` | int | `{{ cfg.default_scan_interval }}` | {{ cfg.scan_interval_min }}–{{ cfg.scan_interval_max }} | Poll interval in seconds |
| `scheduled_reboot` | bool | `true` | — | Enable a daily automatic reboot |
| `reboot_time` | string | `{{ cfg.default_reboot_time }}` | HH:MM | Time of day to reboot the controller |

Changing options triggers a full config entry reload.

Validation: `reboot_time` must be a valid 24-hour `HH:MM` string (e.g. `{{ cfg.default_reboot_time }}`). An `invalid_time` error is shown in the form if the value cannot be parsed.

## Reference

::: custom_components.sunriser.config_flow
