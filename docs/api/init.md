# Integration Setup

`__init__.py` handles integration lifecycle and service registration.

## Lifecycle hooks

| Function | Purpose |
|---|---|
| `async_setup` | Registers the Day Planner Lovelace card JS and all service actions |
| `async_setup_entry` | Creates the coordinator, runs first refresh, defers platform setup until init completes |
| `async_unload_entry` | Unloads all platforms and closes the HTTP session |

## Service actions

| Service | Input | Response | Description |
|---|---|---|---|
| `sunriser.backup` | — | `{path}` | Downloads config to HA config dir as `.msgpack` |
| `sunriser.restore` | `file_path` | — | Restores config from a `.msgpack` file |
| `sunriser.get_errors` | — | `{content}` | Retrieves device error log |
| `sunriser.get_log` | — | `{content}` | Retrieves device diagnostic log |
| `sunriser.get_dayplanner_schedule` | `pwm` | `{pwm, name, color_id, markers}` | Reads day planner schedule |
| `sunriser.set_dayplanner_schedule` | `pwm, markers` | — | Writes day planner schedule |
| `sunriser.get_weekplanner_schedule` | `pwm` | `{pwm, name, color_id, schedule}` | Reads week planner schedule |
| `sunriser.set_weekplanner_schedule` | `pwm, schedule` | — | Writes week planner schedule |
| `sunriser.download_factory_backup` | — | `{path}` | Downloads factory default config |
| `sunriser.download_firmware` | — | `{path}` | Downloads firmware info |
| `sunriser.download_bootload` | — | `{path}` | Downloads bootloader info |
| `sunriser.factory_reset` | `confirm: true` | — | Resets all device config to factory defaults |

## Reference

::: custom_components.sunriser
    options:
      members:
        - async_setup
        - async_setup_entry
        - async_unload_entry
