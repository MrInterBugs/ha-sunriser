# Binary Sensor

A single connectivity binary sensor derived from whether the last `GET /state` succeeded. It does **not** make an independent `GET /ok` request — the coordinator's existing poll result is reused.

The sensor becomes `off` (disconnected) after `_FAILURE_GRACE` (3) consecutive poll failures.

## Reference

::: custom_components.sunriser.binary_sensor
