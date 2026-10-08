# Integration Setup

`__init__.py` handles integration lifecycle and service registration.

## Lifecycle hooks

| Function | Purpose |
|---|---|
| `async_setup` | Registers the Day Planner Lovelace card JS and all service actions |
| `async_setup_entry` | Creates the coordinator, loads configuration, performs the first refresh, and sets up all platforms before returning |
| `async_unload_entry` | Unloads platforms, closes the HTTP session, and cancels the reboot listener |
| `async_remove_entry` | Clears the controller's repair notification and saved DST helper state |

## Service actions

| Service | Input | Response | Description |
|---|---|---|---|
| `sunriser.backup` | — | `{path}` | Downloads config to HA config dir as `.msgpack` |
| `sunriser.restore` | `file_path` | — | Restores config from a `.msgpack` file |
| `sunriser.get_errors` | — | `{content}` | Retrieves device error log |
| `sunriser.get_log` | — | `{content}` | Retrieves device diagnostic log |
| `sunriser.get_planning` | — | `{channels, weekday}` | Reads selected daily/weekly curves and active program names for the read-only card |
| `sunriser.get_dayplanner_schedule` | `pwm` | `{pwm, name, color_id, markers}` | Reads day planner schedule |
| `sunriser.set_dayplanner_schedule` | `pwm, markers` | — | Writes day planner schedule |
| `sunriser.get_weekplanner_schedule` | `pwm` | `{pwm, name, color_id, schedule}` | Reads week planner schedule |
| `sunriser.set_weekplanner_schedule` | `pwm, schedule` | — | Writes week planner schedule |
| `sunriser.download_factory_backup` | — | `{path}` | Downloads configuration preserved by a factory reset |
| `sunriser.download_firmware` | — | `{path}` | Downloads firmware info |
| `sunriser.download_bootload` | — | `{path}` | Downloads bootloader info |
| `sunriser.factory_reset` | `confirm: true` | — | Resets all device config to factory defaults |

All actions accept an optional `device_id` in their data; it is required when multiple controllers are loaded. See [Services](../services.md) for fields and examples.

## Reference

::: custom_components.sunriser
    options:
      members:
        - async_setup
        - async_setup_entry
        - async_unload_entry
        - async_remove_entry
