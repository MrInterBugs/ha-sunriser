# Services

The integration registers the following service actions under the `sunriser` domain.

Every action accepts an optional `device_id` in its `data`. With one loaded
SunRiser controller, existing calls work unchanged. With multiple loaded
controllers, select the Controller field or supply its Home Assistant device ID;
calls without a selection fail rather than operating on an arbitrary controller.
Unloaded entries are excluded, and an explicitly selected unloaded or unknown
device produces an error without falling back to another controller.

The Day Planner card accepts the same `device_id` in its card configuration.

Backup and firmware exports include the controller's entry ID and a unique suffix
in their filenames. Repeated calls create separate files; existing files are never
overwritten. Use the returned `path` when restoring a backup.

Day-planner marker times must be valid clock times (`00:00` through `23:59`);
`24:00` is also accepted as an end-of-day marker.

```yaml
action: sunriser.get_log
data:
  device_id: YOUR_HOME_ASSISTANT_DEVICE_ID
response_variable: result
```

{% for service_id, service in services.items() %}
## {{ service.name }} (`sunriser.{{ service_id }}`)

{{ service.description | trim }}

{{ fields_table(service.fields) }}

{% endfor %}

## Examples

### Backup and restore

```yaml
# Take a backup
action: sunriser.backup
response_variable: result
# result.path contains the unique filename of this backup

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

### Read and write a week planner schedule

```yaml
# Read schedule for PWM channel 1
action: sunriser.get_weekplanner_schedule
data:
  pwm: 1
response_variable: schedule
# schedule.schedule = {"monday": 1, "tuesday": 1, ..., "default": 0}

# Write a new week planner schedule for PWM channel 1
action: sunriser.set_weekplanner_schedule
data:
  pwm: 1
  schedule:
    monday: 1
    tuesday: 1
    wednesday: 1
    thursday: 1
    friday: 1
    saturday: 2
    sunday: 2
    default: 0
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
