# Config Flow

UI-driven setup and options flow.

## Setup parameters

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | — | IP address or hostname of the SunRiser |
| `port` | int | `80` | HTTP port |

The flow tests connectivity before completing — raises an error if the device is unreachable.

## Options parameters

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `scan_interval` | int | `30` | 5–3600 | Poll interval in seconds |

Changing options triggers a full config entry reload.

## Reference

::: custom_components.sunriser.config_flow
