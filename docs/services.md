# Services

The integration registers service actions under the `sunriser` domain.

## Select a controller

Every action accepts `device_id` in its `data`. It is optional with one loaded controller and required with multiple controllers. Select **Controller** in the action form, or copy its HA device ID into YAML. An unknown or unloaded selection returns an error.

```yaml
action: sunriser.get_log
data:
  device_id: YOUR_HOME_ASSISTANT_DEVICE_ID
response_variable: result
```

The [Day Planner card](configuration.md#day-planner-card) uses the same `device_id`.

## Actions

{% for service_id, service in services.items() %}
### {{ service.name }} (`sunriser.{{ service_id }}`)

{{ service.description | trim }}

{{ fields_table(service.fields) }}

{% endfor %}

## Backup and restore

Backup and diagnostic exports return a `path`. Filenames include the controller's entry ID and a unique suffix, so repeated calls do not overwrite existing files. Keep the returned path to identify the file to restore.

Use this action in a script to take a backup:

```yaml
action: sunriser.backup
response_variable: result
```

To restore a chosen backup, replace the placeholder below with that backup's returned `path`. The file must be inside HA's configuration directory or a path allowed by Home Assistant. Add `device_id` to both actions when selecting among multiple controllers.

```yaml
action: sunriser.restore
data:
  file_path: /config/REPLACE_WITH_BACKUP_FILENAME.msgpack
```

### Scheduled backup automation

Paste this into an automation's YAML editor. With multiple controllers, add `data.device_id` to the backup action.

```yaml
alias: SunRiser nightly backup
triggers:
  - trigger: time
    at: "03:00:00"
actions:
  - action: sunriser.backup
mode: single
```

## Week planner schedules

Read a channel's week planner assignments:

```yaml
action: sunriser.get_weekplanner_schedule
data:
  pwm: 1
response_variable: schedule
```

The response includes `pwm`, `name`, `color_id`, and `schedule`. The schedule maps day names to program IDs; an unset assignment can be `null`.

Write a complete set of assignments with the following action. Omitted days are written as `0` (no program); this action does not merge with the previous schedule. Set the channel's Manager to `weekplanner` to use it.

```yaml
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

## Day planner schedules

Read a channel's stored day planner markers from HA's configuration cache:

```yaml
action: sunriser.get_dayplanner_schedule
data:
  pwm: 1
response_variable: schedule
```

The response includes `pwm`, `name`, `color_id`, and `markers`. Marker times run from `00:00` through `23:59`; `24:00` is also accepted for the end of the day. Percentages must be integers from 0 to 100.

This action replaces the markers for channel 1. Set the channel's Manager to `dayplanner` to use them.

```yaml
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

## End maintenance or blackout

Turn off the controller's **Maintenance Mode** switch to end either session.
Automations can use `switch.turn_off` targeting that switch. This leaves stored
configuration and time-lapse unchanged.

## Planning snapshot

`sunriser.get_planning` returns configured channels with their selected daily or
weekly curves, active weekly program names, and the current controller weekday.
It is read-only and powers the Day Planner graph. It supports `device_id`;
selection is required when multiple controllers are loaded. Edit schedules in the
controller interface. Existing day/week service actions are unchanged.
