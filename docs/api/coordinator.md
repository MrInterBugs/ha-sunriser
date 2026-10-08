# Coordinator

The `SunRiserCoordinator` owns the HTTP session, maintains the device configuration cache, and drives polling.

## Polling strategy

Every poll performs these requests sequentially, without artificial delays:

1. `GET /state` — current channel values, uptime, and temperature readings.
2. `GET /weather` — current weather simulation state.
3. `POST /` — firmware identity, channel configuration, sensor metadata, and weather program names in a single MessagePack request.

The configured poll interval defaults to {{ cfg.default_scan_interval }} seconds. The HTTP session reuses connections. Configuration reads through cache publication and configuration writes share a lock to preserve ordering; unrelated requests are not globally serialized. Successful configuration writes update the cache and notify entity listeners immediately.

## Setup

Setup first reads the controller identity and channel count, then performs a complete poll. Platforms are loaded before setup returns, with no waits for later poll ticks. Missing required startup configuration causes Home Assistant to retry setup. Weather is optional and is retried on the next poll.

## Scheduled reboot

Daily reboot is opt-in (default: off). Existing explicit `scheduled_reboot` settings remain effective. When enabled, a daily listener calls `async_reboot()` at the configured `reboot_time` (default `{{ cfg.default_reboot_time }}`). The listener is cancelled in `async_close()` and re-registered on options reload.

## Failure handling

State failures retain the previous snapshot until the failure count reaches {{ cfg.failure_grace }}. The connectivity sensor reports the failed state request immediately; other entities become unavailable on the {{ cfg.failure_grace }}th failure, and a controller-specific repair issue is raised. Only a successful state read establishes recovery. Failed state reads skip weather, configuration, and DST requests for that poll.

After startup, failed weather or configuration reads retain their cached values and are retried next poll. New temperature entities wait for their scaling metadata. Legacy DST synchronization runs after successful state and configuration reads; failed writes are retried on the next successful poll without replacing state polling. Firmware 1.006+ handles DST itself and receives no HA DST writes.

## Reference

::: custom_components.sunriser.coordinator
    options:
      members:
        - SunRiserCoordinator
        - DayplannerMarker
