# Coordinator

The `SunRiserCoordinator` is the central hub of the integration. It owns the HTTP session, maintains the device config cache, and drives all polling.

## Polling strategy

The coordinator uses a staggered round-robin to avoid overwhelming the WizFi360 Wi-Fi module:

```
tick 0: GET /state
tick 1: GET /weather
tick 2: GET /state  ← repeats
...
every 240 ticks (~4 h at 60 s default): one tick is replaced by POST / (re-read PWM config)
```

One HTTP request per poll tick. The `force_close=True` TCP connector ensures the ESP8266 always sees a fresh single-use connection.

## Init sequence

Before normal polling starts, four init ticks run sequentially:

| Tick | Request | Purpose |
|------|---------|---------|
| 0 | `POST /` | Fetch base config (`name`, `model`, `pwm_count`, …) |
| 1 | `GET /state` | Discover sensor ROMs, seed PWM values |
| 2 | `POST /` (one chunk per tick) | Fetch per-channel PWM config and sensor metadata — chunks are drained one per tick to avoid back-to-back TCP connections during startup |
| 3 | `GET /weather` | Fetch initial weather state so entities can be created |

Platform setup is deferred until all init ticks complete (including all chunk ticks for step 2).

## Scheduled reboot

If `scheduled_reboot` is enabled in options (default: on), the coordinator registers a daily `async_track_time_change` listener at the configured `reboot_time` (default `04:00`). At that time it calls `async_reboot()` silently. The listener is cancelled in `async_close()` and re-registered on options reload.

## Failure handling

Connectivity failures are graced for 3 consecutive misses (`_FAILURE_GRACE = 3`). On the third failure a repair issue is raised in HA. Recovery automatically deletes the issue.

## Reference

::: custom_components.sunriser.coordinator
    options:
      members:
        - SunRiserCoordinator
        - DayplannerMarker
