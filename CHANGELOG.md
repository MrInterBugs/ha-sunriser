# Changelog

## [1.6.3-beta.3] - 2026-03-29

### Tests

- Updated coordinator tests to reflect the new pwm_config tick trigger (`_ticks_since_pwm_refresh` counter instead of `_next_refresh_index = 2`); sensor and weather program name fetch tests rewritten as two-tick scenarios (state/weather tick queues keys, pwm_config tick drains them)

## [1.6.3-beta.2] - 2026-03-29

### Fixed

- **Device instability with dynamic entities** — the `pwm_config` slot was added to `_REFRESH_SEQUENCE` in beta.1, which caused the WizFi360 TCP stack to become unresponsive for ~30-minute periods. The sequence is reverted to `(state, weather)` and PWM config is instead refreshed every 60 ticks (~30 min at the default 30 s interval), replacing one normal tick rather than adding an extra request
- **No more double requests per tick** — new DS1820 sensor ROMs and weather program names discovered during state/weather ticks are now queued in `_pending_config_keys` and fetched in bulk on the next pwm_config tick, so no tick ever makes two back-to-back HTTP requests

## [1.6.3-beta.1] - 2026-03-28

### Added

- **Dynamic entity add/remove** — PWM light, switch, number, and select entities are now added and removed at runtime when channels are activated or deactivated on the device, without requiring a full integration reload; DS1820 temperature sensors are also added dynamically as new probes appear

### Changed

- **Staggered polling — one request per tick** — the coordinator round-robin now cycles through three slots (`state → weather → pwm_config`) so every poll tick sends exactly one HTTP request; previously the state tick fired a second `POST /` to re-check PWM config in the same interval, which could race the WizFi360 TCP teardown window

## [1.6.2] - 2026-03-28

### Added

- **Diagnostics** — `diagnostics.py` implements `async_get_config_entry_diagnostics`; redacts the host but exposes coordinator config and state for HA diagnostic reports
- **Entity translations** — `strings.json` and `icons.json` added; all entity names and icons now use translation keys instead of hardcoded strings

### Fixed

- **Password field removed** — the SunRiser device has no authentication mechanism; the `password` field has been removed from the config flow, coordinator, and all tests

### Changed

- **DHCP discovery reloads on IP change** — if a known device is rediscovered with a new IP, the existing config entry is updated and reloaded instead of prompting the user again
- **Fixed value and manager entities disabled by default** — `SunRiserPWMFixedNumber` and `SunRiserPWMManagerSelect` now have `entity_registry_enabled_default = False`. Both are advanced config set once at install time.
- **Uptime sensor disabled by default** — `SunRiserUptimeSensor` changes on every poll and adds noise to history. Enable it manually if needed.

## [1.6.1-beta.1] - 2026-03-27

### Fixed

- **Service action error handling** — all service handlers now raise `HomeAssistantError` on device communication failures (`aiohttp.ClientError`) instead of propagating raw exceptions; file I/O failures in backup/restore/download handlers raise `HomeAssistantError` on `OSError`; `handle_get_weekplanner` also catches `msgpack.UnpackException` for malformed device responses
- **Day planner `None` guard** — `async_get_dayplanner` now skips marker pairs where either value is `None` (a known device quirk where unset config keys return `None`); previously `int(None)` would raise `TypeError`

### Changed

- **Strict type checking** — all Python source files now pass `mypy --strict`; bare `dict`/`list` annotations replaced with fully-typed generics; `DayplannerMarker` TypedDict added to coordinator; service handler response shapes documented as TypedDicts (`_FilePathResponse`, `_ContentResponse`, `_DayplannerScheduleResponse`, `_WeekplannerScheduleResponse`); `EntityCategory` imported from `homeassistant.const`; `ColorMode` imported from `homeassistant.components.light.const`

### Tests

- 18 new tests covering all service handler error paths (`aiohttp.ClientError`, `OSError`, `msgpack.UnpackException`), the day planner `None` guard, and the weekplanner msgpack error path; overall coverage remains at 100%

## [1.6.0] - 2026-03-27

### Fixed

- **Services registered in `async_setup`** — all service actions (`backup`, `restore`, `get_errors`, `get_log`, `get_dayplanner_schedule`, `set_dayplanner_schedule`, `get_weekplanner_schedule`, `set_weekplanner_schedule`, `download_factory_backup`, `download_firmware`, `download_bootload`, `factory_reset`) are now registered once in `async_setup` instead of `async_setup_entry`; prevents duplicate service registration errors when a config entry is reloaded

### Changed

- **4-step init state machine** — replaces `asyncio.sleep()` startup delays with a proper state machine; each of the four init ticks (base config, state, PWM config, weather) makes exactly one HTTP request so the WizFi360 has a full poll interval between connections
- **Deferred platform setup** — entity platforms are not loaded until all four init ticks complete, ensuring PWM names, colors, and weather data are fully populated before any entity is created
- **Sensor ROM discovery during init** — temperature sensor ROMs are discovered in tick 1 (state fetch) and their config keys are batched into the tick 2 request, eliminating a separate config round-trip
- **Request serialisation lock** — `asyncio.Lock` added to the coordinator so only one TCP connection is ever in-flight at a time; prevents concurrent entity writes from crashing the WizFi360 module
- **`PARALLEL_UPDATES`** declared at module level in all platform files — `0` for read-only platforms (`binary_sensor`, `sensor`), `1` for write platforms (`button`, `light`, `number`, `select`, `switch`)
- **Availability logging** — the coordinator now logs a `WARNING` once when the device becomes unavailable (after the grace period) and an `INFO` when it recovers; previously it raised `UpdateFailed` silently on every failed poll without a distinct recovery message
- **Runtime data** — coordinator instance now stored in `ConfigEntry.runtime_data` instead of `hass.data`

## [1.5.4-beta.1 & 1.5.4-beta.2] - 2026-03-26

### Changed

- **Request serialisation lock** — `asyncio.Lock` added to the coordinator so only one TCP connection is ever in-flight at a time; prevents concurrent entity writes from crashing the WizFi360 module

## [1.5.4-beta.0] - 2026-03-26

### Changed

- **4-step init state machine** — replaces `asyncio.sleep()` startup delays with a proper state machine; each of the four init ticks (base config, state, PWM config, weather) makes exactly one HTTP request so the WizFi360 has a full poll interval between connections
- **Deferred platform setup** — entity platforms are not loaded until all four init ticks complete, ensuring PWM names, colors, and weather data are fully populated before any entity is created
- **Sensor ROM discovery during init** — temperature sensor ROMs are discovered in tick 1 (state fetch) and their config keys are batched into the tick 2 request, eliminating a separate config round-trip

## [1.5.3] - 2026-03-26

### Changed

- **Dayplanner schedule caching** — `dayplanner#marker#N` keys are pre-fetched at startup alongside PWM config and served from the coordinator cache; the Lovelace card no longer hits the device on every page load

- **Startup inter-request delays** — 2-second pauses added between each HTTP request during startup (`async_load_device_config` and the initial full snapshot); prevents rapid back-to-back connections overwhelming the WizFi360 on first load

- **Staggered polling** — after the initial startup snapshot, the coordinator now alternates between `/state` and `/weather` refreshes; connectivity (`ok`) is derived from whether the last state fetch succeeded rather than a separate `/ok` ping; eliminates all back-to-back TCP reconnects on WizFi360-based devices

## [1.5.2] - 2026-03-25

### Changed

- **Staggered polling** — after the initial startup snapshot, the coordinator now refreshes only one endpoint per scan interval (`/ok`, `/weather`, `/state` in rotation) instead of hitting all three back-to-back every cycle; reduces rapid successive TCP reconnects on WizFi360-based devices while retaining the last successful values for the endpoints not refreshed on that tick

## [1.5.1] - 2026-03-25

### Added

- **Fixed value number entity** — one `number` entity per active PWM channel exposing `pwm#X#fixed`. Slider from 0–1000 sets the output level used when the channel manager is `fixed`. Writes to the device immediately via `PUT /`.

## [1.5.0] - 2026-03-25

### Added

- **Connectivity binary sensor** — diagnostic `BinarySensorDeviceClass.CONNECTIVITY` entity that reports `true` when `GET /ok` returns `OK` on the latest poll cycle; goes `false` when the device is unreachable
- **`sunriser.get_weekplanner_schedule` service** — reads the week planner program assignment for a PWM channel; returns a dict mapping day names (`sunday`–`saturday`, `default`) to program IDs
- **`sunriser.set_weekplanner_schedule` service** — writes a new week planner schedule for a PWM channel; accepts a dict of day → program ID; missing days default to 0
- **`sunriser.download_factory_backup` service** — downloads the factory default configuration via `GET /factorybackup` and saves it as a timestamped `.msgpack` file in the HA config directory
- **`sunriser.download_firmware` service** — downloads firmware info via `GET /firmware.mp` and saves it as a timestamped `.msgpack` file
- **`sunriser.download_bootload` service** — downloads bootloader info via `GET /bootload.mp` and saves it as a timestamped `.msgpack` file
- **`sunriser.factory_reset` service** — calls `DELETE /` to reset the device to factory defaults; requires `confirm: true` to prevent accidental use

## [1.4.14] - 2026-03-25

### Fixed

- PWM manager option 3 corrected from `celestial` to `fixed` — the real device web UI shows "Fester Wert" (fixed value); `config_def.json` label was wrong

## [1.4.13] - 2026-03-25

### Added

- **PWM Manager select entity** — one `select` entity per active PWM channel exposing `pwm#X#manager`; options are `none`, `dayplanner`, `weekplanner`, `fixed`; changing the selection writes the new value to the device immediately via `PUT /`
- **Poll grace period** — the coordinator now tolerates up to 2 consecutive missed check-ins before marking entities unavailable; on the third consecutive failure entities go unknown as before; eliminates spurious unavailability caused by transient TCP drops on the ESP8266

### Changed

- `pwm#X#manager` is now fetched at startup alongside name, color, onoff, and max

## [1.4.12] - 2026-03-25

### Fixed

- Use `TCPConnector(force_close=True)` for all HTTP requests so the ESP8266 BEE module always receives a fresh single-use TCP connection; persistent keep-alive connections caused the ESP8266 to send the extended AT+IPD format which the MCU firmware cannot parse, hanging the main loop until the watchdog fired and resetting the device

## [1.4.11] - 2026-03-25

### Changed

- Weather sensor state is now a condition string (`thunder`, `rain`, `cloudy`, `moon`, `clear`) instead of the static program ID integer, enabling HA history recording

## [1.4.10] - 2026-03-25

### Changed

- Weather channel sensors now named after the PWM channel (e.g. "Cool White Weather") instead of the generic "Weather Channel X"
- Weather sensor attributes now include `weather_program_name` (resolved from device config) and `thunder_active`, `moon_active`, `clouds_active`, `rain_active` boolean flags; raw opaque state integers (`clouds_state`, `thunder_state`, `moon_state`) are no longer exposed
- Weather program names are lazy-loaded from the device the first time a program ID is seen

## [1.4.0 - 1.4.8] - 2026-03-24

### Added

- **Day Planner custom card** (`sunriser-dayplan-card.js`) — Lovelace card that renders all active PWM schedules as a 24-hour SVG chart using the same LED colours as the firmware web UI; channel names resolved from the device with no manual configuration required
- **`get_dayplanner_schedule`** now returns `name` and `color_id` alongside `pwm` and `markers`
- Unit tests for all dayplanner coordinator methods and service handlers (100% coverage, 145 tests)

### Fixed

- Card registers itself as a proper Lovelace resource via `lovelace.resources` / `ResourceStorageCollection` — visible in Settings → Dashboards → Resources; falls back to `add_extra_js_url` in YAML-mode Lovelace
- Card JS served from `custom_components/sunriser/www/` (picked up by HACS) and registered automatically on integration setup — no manual Lovelace resource entry required
- Card appears in the HA "Add card" picker via `ll-custom-cards-updated` dispatch
- Added `after_dependencies: [frontend, http, lovelace]` and `CONFIG_SCHEMA` to satisfy HACS and hassfest validation

### Changed

- Card refactored to use Lit 3 (`LitElement`, `html`, `css`, `unsafeSVG`) — efficient DOM diffing replaces full shadow DOM teardown on every render
- Card title uses `ha-card`'s native `.header` property; border and grid colours use `var(--divider-color)`; error state styled with `var(--error-color)`

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
