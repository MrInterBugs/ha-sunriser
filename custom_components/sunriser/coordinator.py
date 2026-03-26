# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
import msgpack

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COLOR_NAMES,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANAGER_OPTIONS,
    PWM_MAX,
)

_LOGGER = logging.getLogger(__name__)


class SunRiserCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator that polls /state and holds device config."""

    _REFRESH_SEQUENCE = ("state", "weather")

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._entry_id = entry.entry_id
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.password: str | None = entry.data.get(CONF_PASSWORD)

        # Static device config fetched once at startup and updated on new sensors.
        self.config: dict = {}

        # Number of consecutive poll failures. Entities only go unavailable
        # after this reaches _FAILURE_GRACE (3 missed check-ins).
        self._consecutive_failures: int = 0

        self._session: aiohttp.ClientSession | None = None
        self._next_refresh_index = 0
        self._last_state_refresh_succeeded = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self.config.get("name") or self.host,
            model=self.config.get("model"),
            sw_version=self.config.get("save_version"),
            manufacturer="LEDaquaristik",
            configuration_url=self.base_url,
        )

    # ------------------------------------------------------------------
    # Session / auth
    # ------------------------------------------------------------------

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # force_close=True sends Connection: close on every request so the
            # ESP8266 BEE module always receives a fresh single-use TCP connection.
            # Without this, keep-alive connections cause the ESP8266 to send the
            # extended AT+IPD format (+IPD,<id>,<ip>,<port>,<len>) which the MCU
            # firmware cannot parse, hanging the main loop until the watchdog fires.
            connector = aiohttp.TCPConnector(force_close=True)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def async_close(self) -> None:
        """Close the dedicated HTTP session, if one was created."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def async_authenticate(self) -> None:
        """Send password to device and store the session cookie.

        The device distinguishes a login POST from a config POST by checking
        whether the body exactly equals "password=<password>" (form-encoded).
        No action needed when no password is set (device default).
        """
        if not self.password:
            return
        session = self._get_session()
        async with session.post(
            f"{self.base_url}/",
            data=f"password={self.password}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Low-level API helpers
    # ------------------------------------------------------------------

    async def async_get_config(self, keys: list[str]) -> dict:
        """POST / — read config values for the given keys."""
        session = self._get_session()
        body = msgpack.packb(keys, use_bin_type=True)
        async with session.post(
            f"{self.base_url}/",
            data=body,
            headers={"Content-Type": "application/x-msgpack"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return msgpack.unpackb(await resp.read(), raw=False)

    async def async_set_config(self, params: dict) -> None:
        """PUT / — write config key/value pairs.

        The device requires save_version (set to factory_version) on every write
        so it can track the config lineage. See sunriser_network.js line 120.
        """
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

    async def async_get_state(self) -> dict:
        """GET /state — returns PWM values, sensor readings, uptime, etc."""
        session = self._get_session()
        async with session.get(
            f"{self.base_url}/state",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return msgpack.unpackb(await resp.read(), raw=False)

    async def async_get_weather(self) -> list:
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

    async def async_get_dayplanner(self, pwm: int) -> list[dict]:
        """Read the dayplanner schedule for a PWM channel from the config cache.

        Returns a list of markers in the form [{"time": "HH:MM", "percent": N}, ...],
        sorted by time. Returns an empty list if no schedule is set.
        """
        flat = self.config.get(f"dayplanner#marker#{pwm}") or []
        markers = []
        for i in range(0, len(flat) - 1, 2):
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
        flat = result.get(f"weekplanner#programs#{pwm}") or []
        return {
            day: (int(flat[i]) if i < len(flat) else None)
            for i, day in enumerate(self._WEEK_DAYS)
        }

    async def async_set_weekplanner(self, pwm: int, schedule: dict[str, int]) -> None:
        """Write the weekplanner program assignment for a PWM channel.

        Accepts a dict with day names (sunday..saturday + default) mapped to program IDs.
        Missing days default to 0 (no program).
        """
        flat = [schedule.get(day, 0) for day in self._WEEK_DAYS]
        await self.async_set_config({f"weekplanner#programs#{pwm}": flat})

    async def async_set_dayplanner(self, pwm: int, markers: list[dict]) -> None:
        """Write the dayplanner schedule for a PWM channel.

        Each marker must have "time" (HH:MM) and "percent" (0–100).
        The flat array sent to the device is [daymin, percent, daymin, percent, ...].
        """
        flat: list[int] = []
        for m in markers:
            h, mn = map(int, m["time"].split(":"))
            flat.extend([h * 60 + mn, int(m["percent"])])
        await self.async_set_config({f"dayplanner#marker#{pwm}": flat})
        self.config[f"dayplanner#marker#{pwm}"] = flat

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def async_load_device_config(self) -> None:
        """Fetch static device config (PWM names, onoff flags, etc.).

        Called once during entry setup before the first state poll.
        """
        await self.async_authenticate()

        base_keys = [
            "name",
            "model",
            "model_id",
            "pwm_count",
            "hostname",
            "factory_version",
            "save_version",
        ]
        base = await self.async_get_config(base_keys)
        self.config.update(base)

        # pwm_count may be None on some firmware versions; derive it from
        # the actual pwms dict in state instead, which is always accurate.
        await asyncio.sleep(2)
        state = await self.async_get_state()
        pwm_count: int = base.get("pwm_count") or len(state.get("pwms", {})) or 8
        self.config["pwm_count"] = pwm_count

        pwm_keys: list[str] = []
        for i in range(1, pwm_count + 1):
            pwm_keys += [
                f"pwm#{i}#name",
                f"pwm#{i}#onoff",
                f"pwm#{i}#max",
                f"pwm#{i}#color",
                f"pwm#{i}#manager",
                f"pwm#{i}#fixed",
                f"dayplanner#marker#{i}",
            ]

        await asyncio.sleep(2)
        pwm_config = await self.async_get_config(pwm_keys)
        self.config.update(pwm_config)

    # ------------------------------------------------------------------
    # Coordinator update
    # ------------------------------------------------------------------

    _FAILURE_GRACE = 3

    async def _async_refresh_state(self) -> dict:
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
                return self.data
            raise UpdateFailed(
                f"Error communicating with SunRiser at {self.host}: {err}"
            ) from err

        self._consecutive_failures = 0
        self._last_state_refresh_succeeded = True
        data = dict(self.data or {})
        data.update(state)

        # Fetch config for any sensors that have appeared since last update.
        if state.get("sensors"):
            new_roms = [
                rom
                for rom in state["sensors"]
                if f"sensors#sensor#{rom}#name" not in self.config
            ]
            if new_roms:
                sensor_keys: list[str] = []
                for rom in new_roms:
                    sensor_keys += [
                        f"sensors#sensor#{rom}#name",
                        f"sensors#sensor#{rom}#unit",
                        f"sensors#sensor#{rom}#unitcomma",
                    ]
                try:
                    sensor_config = await self.async_get_config(sensor_keys)
                    self.config.update(sensor_config)
                except aiohttp.ClientError as err:
                    _LOGGER.warning("Could not fetch sensor config: %s", err)

        return data

    async def _async_refresh_weather(self, data: dict) -> dict:
        try:
            weather = await self.async_get_weather()
            data["weather"] = weather

            # Lazy-load names for any weather program IDs we haven't seen before.
            new_ids = [
                ch["weather_program_id"]
                for ch in weather
                if ch is not None
                and ch.get("weather_program_id") is not None
                and f"weather#setup#{ch['weather_program_id']}#name" not in self.config
            ]
            if new_ids:
                name_keys = [f"weather#setup#{pid}#name" for pid in new_ids]
                try:
                    program_config = await self.async_get_config(name_keys)
                    self.config.update(program_config)
                except aiohttp.ClientError as err:
                    _LOGGER.debug("Could not fetch weather program names: %s", err)
        except aiohttp.ClientError as err:
            _LOGGER.debug("Could not fetch weather data: %s", err)
            data.setdefault("weather", [])
        except Exception as err:
            _LOGGER.debug("Unexpected error fetching weather data: %s", err)
            data.setdefault("weather", [])

        return data

    async def _async_refresh_all(self) -> dict:
        """Build an initial full snapshot before switching to round-robin refreshes."""
        data = await self._async_refresh_state()
        data["ok"] = self._last_state_refresh_succeeded
        await asyncio.sleep(2)
        return await self._async_refresh_weather(data)

    async def _async_update_data(self) -> dict:
        if self.data is None:
            data = await self._async_refresh_all()
            self._next_refresh_index = 1
            return data

        refresh_kind = self._REFRESH_SEQUENCE[self._next_refresh_index]

        if refresh_kind == "state":
            data = await self._async_refresh_state()
            data["ok"] = self._last_state_refresh_succeeded
            if not self._last_state_refresh_succeeded:
                return data
        else:
            data = dict(self.data)
            data = await self._async_refresh_weather(data)

        self._next_refresh_index = (self._next_refresh_index + 1) % len(
            self._REFRESH_SEQUENCE
        )

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

    def sensor_unit(self, rom: str) -> int:
        """0 = raw, 1 = celsius."""
        return self.config.get(f"sensors#sensor#{rom}#unit") or 0

    def sensor_unitcomma(self, rom: str) -> int:
        return self.config.get(f"sensors#sensor#{rom}#unitcomma") or 0

    def sensor_value(self, rom: str) -> float | None:
        """Decoded sensor reading, or None if unavailable."""
        if self.data is None:
            return None
        entry = self.data.get("sensors", {}).get(rom)
        if entry is None:
            return None
        raw = entry[1]
        comma = self.sensor_unitcomma(rom)
        return raw / (10**comma) if comma else float(raw)
