# Binary Sensor

A single connectivity binary sensor derived from whether the last `GET /state` succeeded. It does **not** make an independent `GET /ok` request — the coordinator's existing poll result is reused.

The sensor becomes `off` after the first failed state poll. On the {{ cfg.failure_grace }}th consecutive failure, the coordinator marks its entities (including this sensor) unavailable. A successful state poll restores availability and reports `on`.

## Reference

::: custom_components.sunriser.binary_sensor
