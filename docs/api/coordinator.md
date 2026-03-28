# Coordinator

The `SunRiserCoordinator` is the central hub of the integration. It owns the HTTP session, maintains the device config cache, and drives all polling.

## Polling strategy

The coordinator uses a staggered round-robin to avoid overwhelming the WizFi360 Wi-Fi module:

```
tick 0: GET /state
tick 1: GET /weather
tick 2: POST / (re-read PWM config for dynamic entity add/remove)
tick 3: GET /state  ← repeats
...
```

One HTTP request per poll tick. The `force_close=True` TCP connector ensures the ESP8266 always sees a fresh single-use connection.

## Init sequence

Before normal polling starts, four init ticks run sequentially:

| Tick | Request | Purpose |
|------|---------|---------|
| 0 | `POST /` | Fetch base config (`name`, `model`, `pwm_count`, …) |
| 1 | `GET /state` | Discover sensor ROMs, seed PWM values |
| 2 | `POST /` | Fetch per-channel PWM config and sensor metadata |
| 3 | `GET /weather` | Fetch initial weather state so entities can be created |

Platform setup is deferred until all four ticks complete.

## Failure handling

Connectivity failures are graced for 3 consecutive misses (`_FAILURE_GRACE = 3`). On the third failure a repair issue is raised in HA. Recovery automatically deletes the issue.

## Reference

::: custom_components.sunriser.coordinator
    options:
      members:
        - SunRiserCoordinator
        - DayplannerMarker
