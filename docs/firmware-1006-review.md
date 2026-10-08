# HA integration review: firmware 1.006

Reviewed from `main` on 2026-10-08. Changes are confined to the HA integration.

## Read-only controller evidence

Two serialized requests to the real controller returned:

- Configuration: `factory_version: 1.006`, `save_version: 1.006`, `model: null`, `summertime: 1`.
- State: `sunriser: "10"`, `dst_active: true`, `utc_offset: 120`, `planner_offset: 7200`, uptime 40613 seconds, temperature reading `[1, 251]`.

The controller was reachable during this inspection. This does not establish why HA's earlier poll failed. No device settings or outputs were written.

## Implemented

- Firmware reporting uses `factory_version`, not configuration lineage (`save_version`). The screenshot's 1.005 is stale relative to both fields currently returned by the device.
- Periodic configuration reads include the firmware version, and propagate changes to HA's device registry. They retain the existing body-size limit and one-chunk-per-tick behavior. Detection follows the existing 60-tick configuration refresh cadence.
- Firmware 1.006+ no longer receives HA DST writes. Its old DST Auto-Track entity is removed, including its registry entry. Earlier firmware retains the helper.
- Startup retries the same failed configuration chunk, avoiding partial entity configuration after a transient failure.
- Transient state failures return a separate snapshot, preserving the previous published data. Connectivity still reports the last state request's success; the other entities retain the existing three-failure availability grace.
- Beta.2 fixes require a successful state read before restoring availability after that grace period, clean up failed setup attempts, recover dynamic weather and channel entities, interleave older-firmware DST retries with state reads, and support explicit controller selection for services. See the beta.2 changelog for the complete set of fixes, including exports, duplicate setup, configuration ordering, sensor metadata, repairs, schedule validation, and stale entities.

## Remaining candidates

- **Daily reboot defaults to enabled.** Both coordinator setup and the options form default to a daily reboot when the option is absent. Reassess whether this workaround is appropriate for 1.006 before changing existing users' behavior.
- **Control acknowledgement can lag.** Light and switch actions request the next coordinator refresh, which may be a weather/configuration tick rather than a state tick. A queued state refresh could improve feedback while maintaining controller request spacing.
- **PWM range needs protocol confirmation.** The live state contained 1024 on two channels, while HA uses a nominal maximum of 1000. The original UI also uses 1000 for the expert limit. Do not rescale all lights from this observation alone; confirm whether 1024 is a full-on sentinel or a distinct hardware range.
- **Missing model metadata.** The configuration returned no model, but state identifies model 10. A verified mapping could populate device model information.

## Validation

The repository's Docker environment passed 338 mocked tests with 100% statement coverage (1386 statements, none missed), enforced for the validation run with `--cov-fail-under=100`. Regression tests cover restored DST tracking at startup and automatic removal of the obsolete DST entity after a firmware refresh without reloading HA. Black and strict mypy also passed for the integration changes. Real-device tests were excluded because this review authorized inspection, not output-changing test sequences. The changes have not been installed into the running HA instance.
