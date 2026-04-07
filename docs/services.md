# Services

The integration registers the following service actions under the `sunriser` domain.

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
