# Services

The integration registers the following service actions under the `sunriser` domain.

## Reference

| Service | Description |
|---------|-------------|
| `sunriser.backup` | Downloads all device configuration and saves it to `/config/sunriser_backup_<timestamp>.msgpack`. Returns `{"path": "..."}`. |
| `sunriser.restore` | Restores configuration from a `.msgpack` backup file. Requires `file_path` parameter. The device performs a deep restart after applying. |
| `sunriser.get_errors` | Fetches the device error log. Returns `{"content": "..."}`. |
| `sunriser.get_log` | Fetches the device diagnostic log. Returns `{"content": "..."}`. |
| `sunriser.get_dayplanner_schedule` | Returns the day planner schedule for a PWM channel as `{"pwm": N, "name": "...", "markers": [{"time": "HH:MM", "percent": N}, ...]}`. Served from cache — no device request. |
| `sunriser.set_dayplanner_schedule` | Writes a new day planner schedule for a PWM channel. Accepts `pwm` and a list of `{time, percent}` markers. Changes persist across reboots. |
| `sunriser.get_weekplanner_schedule` | Returns the week planner program assignment for a PWM channel as a dict mapping day names (`sunday`–`saturday`, `default`) to program IDs. |
| `sunriser.set_weekplanner_schedule` | Writes a new week planner schedule for a PWM channel. Accepts `pwm` and a dict of day → program ID. Missing days default to 0. |
| `sunriser.download_factory_backup` | Downloads the factory default configuration via `GET /factorybackup` and saves it as a timestamped `.msgpack` file in the HA config directory. |
| `sunriser.download_firmware` | Downloads firmware info via `GET /firmware.mp` and saves it as a timestamped `.msgpack` file. |
| `sunriser.download_bootload` | Downloads bootloader info via `GET /bootload.mp` and saves it as a timestamped `.msgpack` file. |
| `sunriser.factory_reset` | Resets the device to factory defaults via `DELETE /`. Requires `confirm: true` to prevent accidental use. |

## Examples

### Backup and restore

```yaml
# Take a backup
action: sunriser.backup
response_variable: result
# result.path = /config/sunriser_backup_20260323_120000.msgpack

# Restore from backup
action: sunriser.restore
data:
  file_path: /config/sunriser_backup_20260323_120000.msgpack
```

### Scheduled backup automation

```yaml
automation:
  alias: "SunRiser nightly backup"
  trigger:
    - platform: time
      at: "03:00:00"
  action:
    - action: sunriser.backup
```

### Read and write a day planner schedule

```yaml
# Read schedule for PWM channel 1
action: sunriser.get_dayplanner_schedule
data:
  pwm: 1
response_variable: schedule

# Write a new schedule for PWM channel 1
action: sunriser.set_dayplanner_schedule
data:
  pwm: 1
  markers:
    - time: "06:00"
      percent: 0
    - time: "08:00"
      percent: 80
    - time: "20:00"
      percent: 80
    - time: "22:00"
      percent: 0
```
