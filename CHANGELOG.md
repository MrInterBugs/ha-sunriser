# Changelog

## [1.1.0] - 2026-03-23

### Changed

- **Weather channel attributes** now expose `*_next_change_at` / `*_next_at` as UTC ISO datetimes (e.g. `moon_next_change_at: 2026-03-24T00:27:39+00:00`) computed from device uptime ticks — usable directly in HA automations via `| as_datetime`
- Inactive tick fields (value = 0) render as `None` instead of a meaningless past datetime
- Renamed ambiguous raw keys: `cloudticks → cloud_ticks`, `rainmins → rain_duration_mins`, `rainfront_start/length → *_tick`, `stormfront_start/length → *_tick`, `daycount → day_count`

## [1.0.6] - 2026-03-23

### Updated

- **Weather simulation sensor** now creates one entity per PWM channel that has a weather program assigned (e.g. `Weather Channel 2`), instead of a single aggregate count sensor
- Each weather channel sensor state = `weather_program_id`; all other fields (`clouds_state`, `cloudticks`, `rainfront_start`, `rainmins`, `moon_state`, etc.) exposed as entity attributes

## [1.0.5] - 2026-03-23

### Added

- **Weather simulation sensor** — new `SunRiserWeatherSensor` entity reading from `GET /weather`; reports the active weather program state per device (endpoint is still under development, failures are non-fatal)
- Expanded unit test coverage for coordinator weather fetching (`test_coordinator.py`), device helper (`test_device.py`), and sensor entities (`test_sensor.py`)

### Fixed

- `manifest.json` version bumped to match CHANGELOG (was stuck at 1.0.3 after the 1.0.4 release)

## [1.0.4] - 2026-03-23

### Added

- Unit test suite covering all integration modules (brightness, config flow, coordinator, init, light, sensor, switch)
- GitHub Actions CI job to run the test suite on every push

### Fixed

- Fixed unclosed `aiohttp.ClientSession` resource leak on entry unload

## [1.0.3] - 2026-03-23

### Fixed

- Fixed brightness scaling: only PWM 1000 reports 100%, and PWM 1–3 no longer reports 0% when on
- Fixed `manifest.json` key ordering (`quality_scale` before `requirements`) to pass hassfest

### Added

- `quality_scale: "bronze"` in `manifest.json`
- `single_config_entry: true` in `manifest.json` — prevents duplicate device entries

## [1.0.2] - 2026-03-23

### Changed

- Added `SPDX-License-Identifier: GPL-3.0-or-later` header to all Python source files
- Added `LICENSE` file (GNU GPL v3)
- Corrected README attribution — upstream source code is GPL v3, not CC BY 4.0
- Added `requirements.txt` for development dependencies (msgpack, aiohttp, pytest, black)
- Added `.gitignore`
- Removed `render_readme` from `hacs.json` (no longer a valid HACS field)
- Fixed `manifest.json` key ordering to satisfy hassfest (`domain`, `name`, then alphabetical)
- Added hassfest and Black formatting jobs to the GitHub Actions validation workflow
- Updated GitHub Actions to `actions/checkout@v5` and `actions/setup-python@v6` (Node.js 24)

## [1.0.1] - 2026-03-22

### Changed

- Added `issue_tracker` and `integration_type` fields to `manifest.json` for HACS compliance
- Added HACS validation GitHub Actions workflow (runs on push and pull request)
- Added brand icon (`custom_components/sunriser/brand/icon.png`) so HACS displays an icon
- Added attribution section to README for CC BY 4.0 compliance with the upstream SunRiser source

## [1.0.0] - 2026-03-22

Initial release.

### Added

- **Light** entities for dimmable PWM channels (`pwm#X#onoff = false`), with brightness control mapped from HA 0–255 to device 0–1000
- **Switch** entities for on/off PWM channels (`pwm#X#onoff = true`) and a **Maintenance Mode** switch
- **Sensor** entities: DS1820 temperature sensors (auto-discovered from state), plus diagnostic sensors for Uptime, Firmware Version, and Hostname
- **Config flow** — UI setup collecting host, port, and optional password
- **Options flow** — configurable poll interval (5–3600 s, default 30 s); changing the interval reloads the integration without re-adding it
- PWM channel names resolved from `pwm#X#color` via a built-in colour ID → display name mapping (e.g. `4500k` → "4500K White", `pump` → "Pump")
- Unused channels (`pwm#X#color = ""`) are skipped — no entities created
- `configuration_url` in device info — HA shows a "Visit device" link to the SunRiser web UI
- Availability tracking — all entities go unavailable when the device is unreachable and recover automatically
- `save_version` (firmware version) included in every config write as required by the device
