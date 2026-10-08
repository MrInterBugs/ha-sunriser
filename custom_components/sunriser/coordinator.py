# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypedDict, cast

import aiohttp
import msgpack
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    COLOR_NAMES,
    CONF_REBOOT_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULED_REBOOT,
    DEFAULT_PORT,
    DEFAULT_REBOOT_TIME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class DayplannerMarker(TypedDict):
    time: str
    percent: int


class SunRiserCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Coordinator that polls /state and holds device config."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry_id = entry.entry_id
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data.get(CONF_PORT, DEFAULT_PORT)

        # Device configuration refreshed alongside state and weather.
        self.config: dict[str, Any] = {}

        # Number of consecutive poll failures. Entities only go unavailable
        # after this reaches _FAILURE_GRACE (3 missed check-ins).
        self._consecutive_failures: int = 0

        self._session: aiohttp.ClientSession | None = None
        # Serialize config reads through cache publication with config writes.
        # Other HTTP requests need no artificial spacing or global lock.
        self._config_lock = asyncio.Lock()
        self._last_state_refresh_succeeded = False

        # DST auto-tracking — when enabled the coordinator syncs the device's
        # summertime config key to the actual HA timezone DST state.
        #
        # Restored from hass.data bridge on same-session reloads (e.g. options
        # change).  RestoreEntity in switch.py handles HA restarts via recorder.
        _bridge: dict[str, Any] = hass.data.get(DOMAIN, {})
        self.dst_auto_track: bool = bool(
            _bridge.pop(f"{entry.entry_id}_dst_auto_track", False)
        )
        self._last_known_dst: bool | None = None

        self._scheduled_reboot_cancel: Callable[[], None] | None = None
        self._setup_scheduled_reboot(entry)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry_id)},
            name=self.config.get("name") or self.config.get("model") or self.host,
            model=self.config.get("model"),
            sw_version=self.firmware_version,
            manufacturer="LEDaquaristik",
            configuration_url=self.base_url,
        )

    @property
    def firmware_version(self) -> str | None:
        """Running firmware, distinct from the saved configuration version."""
        return self.config.get("factory_version") or None

    @property
    def firmware_handles_dst(self) -> bool:
        """Firmware 1.006 and later handle DST without HA configuration writes."""
        try:
            return tuple(
                int(part) for part in (self.firmware_version or "").split(".")
            ) >= (1, 6)
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_close(self) -> None:
        """Close the dedicated HTTP session, if one was created."""
        if self._scheduled_reboot_cancel is not None:
            self._scheduled_reboot_cancel()
            self._scheduled_reboot_cancel = None
        if self._session and not self._session.closed:
            await self._session.close()

    def _setup_scheduled_reboot(self, entry: ConfigEntry) -> None:
        """Register a daily time-based reboot if enabled in options."""
        if not entry.options.get(CONF_SCHEDULED_REBOOT, False):
            return
        time_str = entry.options.get(CONF_REBOOT_TIME, DEFAULT_REBOOT_TIME)
        try:
            hour, minute = (int(p) for p in time_str.split(":"))
        except (ValueError, AttributeError):
            _LOGGER.warning(
                "SunRiser: invalid scheduled reboot time %r — skipping", time_str
            )
            return

        @callback
        def _trigger(_now: datetime) -> None:
            _LOGGER.info("SunRiser: scheduled reboot at %s", time_str)
            self.hass.async_create_task(self._async_do_scheduled_reboot())

        self._scheduled_reboot_cancel = async_track_time_change(
            self.hass, _trigger, hour=hour, minute=minute, second=0
        )

    async def _async_do_scheduled_reboot(self) -> None:
        try:
            await self.async_reboot()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("SunRiser: scheduled reboot failed: %s", err)

    # ------------------------------------------------------------------
    # Low-level API helpers
    # ------------------------------------------------------------------

    async def async_get_config(self, keys: list[str]) -> dict[str, Any]:
        """POST / — read config values for a single batch of keys."""
        session = self._get_session()
        body = msgpack.packb(keys, use_bin_type=True)
        async with session.post(
            f"{self.base_url}/",
            data=body,
            headers={"Content-Type": "application/x-msgpack"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return cast(dict[str, Any], msgpack.unpackb(await resp.read(), raw=False))

    async def async_set_config(self, params: dict[str, Any]) -> None:
        """PUT / — write config key/value pairs.

        The device requires save_version (set to factory_version) on every write
        so it can track the config lineage. See sunriser_network.js line 120.
        """
        async with self._config_lock:
            payload = dict(params)
            factory_version = self.config.get("factory_version")
            if factory_version:
                payload["save_version"] = factory_version
            session = self._get_session()
            body = msgpack.packb(payload, use_bin_type=True)
            async with session.put(
                f"{self.base_url}/",
                data=body,
                headers={"Content-Type": "application/x-msgpack"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()

            self.update_config_cache(payload)

    @callback
    def update_config_cache(self, params: dict[str, Any]) -> None:
        """Apply a configuration write only after the controller acknowledges it."""
        self.config.update(params)
        self.async_update_listeners()

    async def async_get_state(self) -> dict[str, Any]:
        """GET /state — returns PWM values, sensor readings, uptime, etc."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/state",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return cast(dict[str, Any], msgpack.unpackb(await resp.read(), raw=False))

    async def async_get_weather(self) -> list[Any]:
        """GET /weather — returns per-channel weather simulation state.

        The response is a msgpack stream whose first object is a list with one
        entry per PWM channel.  Each entry is either None (no weather program
        assigned) or a dict with keys such as weather_program_id, clouds_state,
        cloudticks, clouds_next_state_tick, rainfront_start, rainfront_length,
        rainmins, rain_next_tick, moon_state, moon_next_state_tick.
        """
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/weather",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            unpacker = msgpack.Unpacker(raw=False)
            unpacker.feed(await resp.read())
            return next(iter(unpacker), None) or []

    async def async_set_service_mode(self, enabled: bool) -> None:
        """PUT /state — enable or disable maintenance mode.

        When enabled the device stores the current timestamp in service_mode
        and freezes all PWM channels (except those with pwm#X#nomaint = true).
        When disabled it stores 0.
        """
        session = self._get_session()
        # Device expects integer 1/0 — msgpack boolean True causes a 500.
        body = msgpack.packb({"service_mode": 1 if enabled else 0}, use_bin_type=True)
        async with session.put(
            f"{self.base_url}/state",
            data=body,
            headers={"Content-Type": "application/x-msgpack"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()

    async def async_set_timewarp(self, enabled: bool) -> None:
        """PUT /state — activate or deactivate time-lapse (timewarp) mode.

        When active the device runs the day/week planner at ~1800× speed.
        Weather simulation is suspended while time-lapse is active.
        Device expects integer 1/0 — msgpack boolean causes a 500.
        """
        session = self._get_session()
        body = msgpack.packb({"timewarp": 1 if enabled else 0}, use_bin_type=True)
        async with session.put(
            f"{self.base_url}/state",
            data=body,
            headers={"Content-Type": "application/x-msgpack"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()

    async def async_set_dst_auto_track(self, enabled: bool) -> None:
        """Enable legacy DST tracking and synchronize immediately when enabled."""
        self.dst_auto_track = enabled and not self.firmware_handles_dst
        if self.dst_auto_track:
            is_dst = bool(dt_util.now().dst())
            await self.async_set_config({"summertime": 1 if is_dst else 0})
            self._last_known_dst = is_dst

    async def _async_sync_dst(self) -> None:
        """Sync legacy firmware after a successful poll; retry failures next poll."""
        if self.firmware_handles_dst or not self.dst_auto_track:
            return
        is_dst = bool(dt_util.now().dst())
        if is_dst == self._last_known_dst:
            return
        try:
            await self.async_set_config({"summertime": 1 if is_dst else 0})
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("Could not sync DST to device: %s", err)
        else:
            self._last_known_dst = is_dst

    async def async_set_pwms(self, pwm_values: dict[str, int]) -> None:
        """PUT /state — set PWM channels immediately.

        Values are 0–1000. Note: if a program is running, it will resume
        control after ~1 minute. Use async_set_config with dayplanner keys
        for persistent changes.
        """
        session = self._get_session()
        body = msgpack.packb({"pwms": pwm_values}, use_bin_type=True)
        async with session.put(
            f"{self.base_url}/state",
            data=body,
            headers={"Content-Type": "application/x-msgpack"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()

    async def async_check_ok(self) -> bool:
        """GET /ok — returns True if device responds with 'OK'."""
        session = self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/ok",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200 and (await resp.text()).strip() == "OK"
        except Exception:
            return False

    async def async_reboot(self) -> None:
        """GET /reboot — initiate a device reboot."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/reboot",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()

    async def async_get_factory_backup(self) -> bytes:
        """GET /factorybackup — download the factory default configuration as msgpack bytes."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/factorybackup",
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def async_get_firmware(self) -> bytes:
        """GET /firmware.mp — download firmware info as msgpack bytes."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/firmware.mp",
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def async_get_bootload(self) -> bytes:
        """GET /bootload.mp — download bootloader info as msgpack bytes."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/bootload.mp",
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def async_factory_reset(self) -> None:
        """DELETE / — reset all device configuration to factory defaults."""
        session = self._get_session()
        async with session.delete(
            f"{self.base_url}/",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()

    async def async_get_backup(self) -> bytes:
        """GET /backup — download complete device configuration as msgpack bytes."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/backup",
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def async_restore(self, data: bytes) -> None:
        """PUT /restore — restore device configuration from msgpack backup bytes.

        Unlike PUT /, this triggers a deeper device restart after applying config.
        """
        session = self._get_session()
        async with session.put(
            f"{self.base_url}/restore",
            data=data,
            headers={"Content-Type": "application/x-msgpack"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()

    async def async_get_errors(self) -> str:
        """GET /errors — retrieve the device error log."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/errors",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def async_get_log(self) -> str:
        """GET /log — retrieve the device diagnostic log."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/log",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def async_get_dayplanner(self, pwm: int) -> list[DayplannerMarker]:
        """Read the dayplanner schedule for a PWM channel from the config cache.

        Returns a list of markers in the form [{"time": "HH:MM", "percent": N}, ...],
        sorted by time. Returns an empty list if no schedule is set.
        """
        flat: list[Any] = self.config.get(f"dayplanner#marker#{pwm}") or []
        markers: list[DayplannerMarker] = []
        for i in range(0, len(flat) - 1, 2):
            if flat[i] is None or flat[i + 1] is None:
                continue
            daymin = int(flat[i])
            markers.append(
                {
                    "time": f"{daymin // 60:02d}:{daymin % 60:02d}",
                    "percent": int(flat[i + 1]),
                }
            )
        markers.sort(key=lambda m: m["time"])
        return markers

    _WEEK_DAYS = [
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "default",
    ]

    async def async_get_weekplanner(self, pwm: int) -> dict[str, int | None]:
        """Read the weekplanner program assignment for a PWM channel.

        Returns a dict mapping day names to program IDs.
        Day order matches the device: sunday(0)..saturday(6), default(7).
        'default' is the fallback program used on days with no explicit assignment.
        """
        result = await self.async_get_config([f"weekplanner#programs#{pwm}"])
        flat: list[Any] = result.get(f"weekplanner#programs#{pwm}") or []
        return {
            day: (int(flat[i]) if i < len(flat) and flat[i] is not None else None)
            for i, day in enumerate(self._WEEK_DAYS)
        }

    async def async_set_weekplanner(self, pwm: int, schedule: dict[str, int]) -> None:
        """Write the weekplanner program assignment for a PWM channel.

        Accepts a dict with day names (sunday..saturday + default) mapped to program IDs.
        Missing days default to 0 (no program).
        """
        flat = [schedule.get(day, 0) for day in self._WEEK_DAYS]
        await self.async_set_config({f"weekplanner#programs#{pwm}": flat})

    async def async_set_dayplanner(
        self, pwm: int, markers: list[DayplannerMarker]
    ) -> None:
        """Write the dayplanner schedule for a PWM channel.

        Each marker must have "time" (HH:MM) and "percent" (0–100).
        The flat array sent to the device is [daymin, percent, daymin, percent, ...].
        """
        flat: list[int] = []
        for m in markers:
            h, mn = map(int, m["time"].split(":"))
            flat.extend([h * 60 + mn, int(m["percent"])])
        await self.async_set_config({f"dayplanner#marker#{pwm}": flat})

    _BASE_CONFIG_KEYS: list[str] = [
        "name",
        "model",
        "model_id",
        "pwm_count",
        "hostname",
        "factory_version",
        "save_version",
    ]

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def async_load_device_config(self) -> None:
        """Read the controller identity and channel count during setup."""
        async with self._config_lock:
            self._apply_config(await self.async_get_config(self._BASE_CONFIG_KEYS))

    @callback
    def _apply_config(self, fresh: dict[str, Any]) -> None:
        """Publish config and keep the firmware registry and DST helper current."""
        self.config.update(fresh)
        device = device_registry.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.entry_id)}
        )
        if device is not None and device.sw_version != self.firmware_version:
            device_registry.async_get(self.hass).async_update_device(
                device.id, sw_version=self.firmware_version
            )
        if self.firmware_handles_dst:
            self.dst_auto_track = False

    async def _async_refresh_config(self, data: dict[str, Any]) -> None:
        """Read channel and sensor metadata in one request, then publish it."""
        pwm_count = self.config.get("pwm_count") or len(data.get("pwms", {})) or 8
        keys = list(self._BASE_CONFIG_KEYS)
        for channel in range(1, pwm_count + 1):
            keys.extend(
                f"pwm#{channel}#{key}"
                for key in ("name", "onoff", "max", "color", "manager", "fixed")
            )
            keys.append(f"dayplanner#marker#{channel}")
        for rom in data.get("sensors", {}):
            keys.extend(
                f"sensors#sensor#{rom}#{key}" for key in ("name", "unit", "unitcomma")
            )
        program_ids = {
            channel["weather_program_id"]
            for channel in data.get("weather", [])
            if channel is not None and channel.get("weather_program_id") is not None
        }
        keys.extend(f"weather#setup#{pid}#name" for pid in sorted(program_ids))
        async with self._config_lock:
            fresh = await self.async_get_config(keys)
            # Some controllers omit their channel count from configuration.
            fresh["pwm_count"] = fresh.get("pwm_count") or pwm_count
            self._apply_config(fresh)

    # ------------------------------------------------------------------
    # Coordinator update
    # ------------------------------------------------------------------

    _FAILURE_GRACE = 3

    async def _async_refresh_state(self) -> dict[str, Any]:
        try:
            state = await self.async_get_state()
        except (aiohttp.ClientError, Exception) as err:
            self._last_state_refresh_succeeded = False
            self._consecutive_failures += 1
            if (
                self.data is not None
                and self._consecutive_failures < self._FAILURE_GRACE
            ):
                _LOGGER.debug(
                    "SunRiser poll failed (%d/%d), returning stale data: %s",
                    self._consecutive_failures,
                    self._FAILURE_GRACE,
                    err,
                )
                return dict(self.data)
            if (
                self.data is not None
                and self._consecutive_failures == self._FAILURE_GRACE
            ):
                _LOGGER.warning(
                    "SunRiser at %s is unavailable after %d consecutive poll failures",
                    self.host,
                    self._FAILURE_GRACE,
                )
                async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"device_unreachable_{self.entry_id}",
                    is_fixable=False,
                    severity=IssueSeverity.WARNING,
                    translation_key="device_unreachable",
                    translation_placeholders={"host": self.host},
                )
            raise UpdateFailed(
                f"Error communicating with SunRiser at {self.host}: {err}"
            ) from err

        if self._consecutive_failures >= self._FAILURE_GRACE:
            _LOGGER.info("SunRiser at %s is available again", self.host)
        # Repairs persist across coordinator reloads; the counter does not.
        async_delete_issue(self.hass, DOMAIN, f"device_unreachable_{self.entry_id}")
        self._consecutive_failures = 0
        self._last_state_refresh_succeeded = True
        data = dict(self.data or {})
        data["timewarp"] = 0  # reset before merge; device omits the key when inactive
        data.update(state)

        return data

    async def _async_refresh_weather(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            weather = await self.async_get_weather()
            data["weather"] = weather

        except aiohttp.ClientError as err:
            _LOGGER.debug("Could not fetch weather data: %s", err)
            data.setdefault("weather", [])
        except Exception as err:
            _LOGGER.debug("Unexpected error fetching weather data: %s", err)
            data.setdefault("weather", [])

        return data

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._async_refresh_state()
        data["ok"] = self._last_state_refresh_succeeded
        if not self._last_state_refresh_succeeded:
            return data

        await self._async_refresh_weather(data)
        try:
            await self._async_refresh_config(data)
        except Exception as err:
            if self.data is None:
                # Do not create entities from incomplete startup metadata.
                raise UpdateFailed(
                    f"Could not load SunRiser configuration: {err}"
                ) from err
            _LOGGER.debug("Could not refresh device config: %s", err)
        else:
            # Refresh firmware first so an upgrade cannot trigger a legacy DST write.
            await self._async_sync_dst()
        return data

    # ------------------------------------------------------------------
    # Convenience helpers for entities
    # ------------------------------------------------------------------

    @property
    def pwm_count(self) -> int:
        return self.config.get("pwm_count") or 8

    def pwm_name(self, pwm_num: int) -> str:
        color_id = self.config.get(f"pwm#{pwm_num}#color") or ""
        return (
            self.config.get(f"pwm#{pwm_num}#name")
            or COLOR_NAMES.get(color_id)
            or f"PWM {pwm_num}"
        )

    def pwm_is_onoff(self, pwm_num: int) -> bool:
        return bool(self.config.get(f"pwm#{pwm_num}#onoff", False))

    def pwm_manager(self, pwm_num: int) -> int:
        """Return the manager integer for a PWM channel (0–3)."""
        return self.config.get(f"pwm#{pwm_num}#manager") or 0

    def pwm_is_unused(self, pwm_num: int) -> bool:
        return not (self.config.get(f"pwm#{pwm_num}#color") or "")

    def pwm_value(self, pwm_num: int) -> int:
        """Current PWM value (0–1000) from latest state."""
        if self.data is None:
            return 0
        return self.data.get("pwms", {}).get(str(pwm_num)) or 0

    def weather_program_name(self, program_id: int | None) -> str | None:
        if program_id is None:
            return None
        return self.config.get(f"weather#setup#{program_id}#name") or None

    def sensor_name(self, rom: str) -> str:
        return self.config.get(f"sensors#sensor#{rom}#name") or rom

    def sensor_config_loaded(self, rom: str) -> bool:
        """Whether sensor naming, units and scaling have actually been fetched."""
        return all(
            f"sensors#sensor#{rom}#{key}" in self.config
            for key in ("name", "unit", "unitcomma")
        )

    def sensor_unit(self, rom: str) -> int:
        """0 = raw, 1 = celsius."""
        return self.config.get(f"sensors#sensor#{rom}#unit") or 0

    def sensor_unitcomma(self, rom: str) -> int:
        return self.config.get(f"sensors#sensor#{rom}#unitcomma") or 0

    def sensor_value(self, rom: str) -> float | None:
        """Decoded sensor reading, or None if unavailable."""
        if self.data is None or not self.sensor_config_loaded(rom):
            return None
        entry = self.data.get("sensors", {}).get(rom)
        if entry is None:
            return None
        raw = entry[1]
        comma = self.sensor_unitcomma(rom)
        return raw / (10**comma) if comma else float(raw)
