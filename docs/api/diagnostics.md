# Diagnostics

Implements `async_get_config_entry_diagnostics` so HA can include integration state in diagnostic reports.

The response contains:

- `config_entry`: connection settings (host and port).
- `coordinator_config`: the cached device configuration.
- `coordinator_state`: the latest state and weather snapshot.
- `last_update_success`: the coordinator's update status.

The integration does not redact these fields. Review the downloaded file before sharing it; it includes local network details and device configuration.

## Reference

::: custom_components.sunriser.diagnostics
