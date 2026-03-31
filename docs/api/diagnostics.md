# Diagnostics

Implements `async_get_config_entry_diagnostics` so HA can include integration state in diagnostic reports.

The returned dict includes the coordinator's live `data` snapshot and sanitised `config` (credentials redacted).

## Reference

::: custom_components.sunriser.diagnostics
