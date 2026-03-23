# Changelog

## [1.4.2] - 2026-03-23

### Fixed

- Day Planner card now works after HACS installation with no manual steps — the card JS has moved from `www/` (ignored by HACS) into `custom_components/sunriser/www/` and is registered automatically via `async_setup` using `add_extra_js_url`; no Lovelace resource entry required

## [1.4.1] - 2026-03-23

### Fixed

- Custom card now appears in the HA "Add card" picker — dispatches `ll-custom-cards-updated` to handle the race condition where the JS module loads after the picker is initialised; added `preview: true` to the card registration

## [1.4.0] - 2026-03-23

### Added

- **Day Planner custom card** (`www/sunriser-dayplan-card.js`) — Lovelace card that renders all active PWM schedules as a 24-hour SVG chart; uses the same LED colours as the firmware web UI; channel names resolved from the device (e.g. "TROPIC 4500K") with no manual configuration required
- **`get_dayplanner_schedule` response enriched** — now returns `name` (resolved channel name) and `color_id` (LED colour identifier) alongside `pwm` and `markers`, making the response self-describing for automations and the custom card

## [1.3.1] - 2026-03-23

### Added

- **`sunriser.get_dayplanner_schedule` service** — reads the day planner schedule for a PWM channel; returns `{"pwm": N, "markers": [{"time": "HH:MM", "percent": N}, ...]}` sorted by time
- **`sunriser.set_dayplanner_schedule` service** — writes a new day planner schedule for a PWM channel; accepts a list of `{time, percent}` markers which the device interpolates linearly; changes persist across reboots (unlike direct PWM state writes which revert after ~1 minute)
- Both services documented in `services.yaml` with HA UI selectors

## [1.2.1] - 2026-03-23

### Fixed

- `sunriser.restore` now accepts backup files saved by `sunriser.backup` — HA's `allowlist_external_dirs` does not include the config directory by default, so the path check now also allows any file inside the HA config directory

## [1.2.0] - 2026-03-23

### Added

- **Reboot button** — new `button` entity (`Reboot`) that calls `GET /reboot` to restart the device directly from HA; uses `ButtonDeviceClass.RESTART` and `EntityCategory.CONFIG`
- **`sunriser.backup` service** — calls `GET /backup`, saves the full device configuration as a `.msgpack` file in `/config/`, and returns `{"path": "..."}` for use in automations
- **`sunriser.restore` service** — reads a `.msgpack` backup file and calls `PUT /restore`, which applies the config and triggers a deep device restart; requires `file_path` parameter
- **`sunriser.get_errors` service** — calls `GET /errors` and returns `{"content": "..."}` with the device error log
- **`sunriser.get_log` service** — calls `GET /log` and returns `{"content": "..."}` with the device diagnostic log
- `services.yaml` with descriptions and field selectors for all four new services

## [1.1.1] - 2026-03-23

### Added

- **DHCP discovery** — devices with a hostname matching `sunriser*` are automatically discovered when they join the network; HA shows a confirmation prompt before adding the entry
- MAC address used as unique ID so a device IP change is handled silently (existing entry updated, no user action needed)

### Fixed

- `DhcpServiceInfo` imported from `homeassistant.helpers.service_info.dhcp` instead of the full DHCP component, avoiding the `aiodhcpwatcher` dependency in tests

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
