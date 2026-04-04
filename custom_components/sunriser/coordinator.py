# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import aiohttp
import msgpack

from typing import Any, TypedDict, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COLOR_NAMES,
    CONF_REBOOT_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULED_REBOOT,
    DEFAULT_PORT,
    DEFAULT_REBOOT_TIME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANAGER_OPTIONS,
    PWM_MAX,
)

_LOGGER = logging.getLogger(__name__)


class DayplannerMarker(TypedDict):
    time: str
    percent: int


class SunRiserCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls /state and holds device config."""

    _REFRESH_SEQUENCE = ("state", "weather")
    _MAX_CONFIG_REQUEST_BODY_BYTES = 450
    # How many normal ticks between PWM config refreshes.  Each tick is one HTTP
    # request; the WizFi360 TCP stack becomes unresponsive if POST / (the config
    # read endpoint) fires too frequently.  240 ticks ≈ 4 h at the default 60 s
    # scan interval — frequent enough to detect channel changes within a session,
    # rare enough not to stress the WiFi module.
    _PWM_CONFIG_INTERVAL = 240

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

        # Static device config fetched once at startup and updated on new sensors.
        self.config: dict[str, Any] = {}

        # Number of consecutive poll failures. Entities only go unavailable
        # after this reaches _FAILURE_GRACE (3 missed check-ins).
        self._consecutive_failures: int = 0

        self._session: aiohttp.ClientSession | None = None
        self._request_lock = asyncio.Lock()
        self._next_refresh_index = 0
        self._last_state_refresh_succeeded = False
        self._init_step: int = 0
        self._pending_sensor_roms: list[str] = []
        self._ticks_since_pwm_refresh: int = 0
        # Config keys discovered during state/weather ticks that need fetching.
        # Drained on the next pwm_config tick so no tick ever makes two requests.
        self._pending_config_keys: set[str] = set()
        # PWM config refresh chunks queued by _enqueue_pwm_refresh; drained one
        # per tick by _async_drain_one_refresh_chunk to preserve the one-request-
        # per-tick contract even when the full key list spans multiple chunks.
        self._pending_refresh_chunks: list[list[str]] = []
        self._refresh_accumulator: dict[str, Any] = {}

        # DST auto-tracking — when enabled the coordinator syncs the device's
        # summertime config key to the actual HA timezone DST state.
        # _dst_sync_pending is set when a DST transition is detected; the sync
        # then replaces the next poll tick (one request, no double-request).
        self._dst_auto_track: bool = False
        self._last_known_dst: bool | None = None
        self._dst_sync_pending: bool = False

        self._scheduled_reboot_cancel: Callable[[], None] | None = None
        self._setup_scheduled_reboot(entry)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self.config.get("name") or self.config.get("model") or self.host,
            model=self.config.get("model"),
            sw_version=self.config.get("save_version"),
            manufacturer="LEDaquaristik",
            configuration_url=self.base_url,
        )

    # ------------------------------------------------------------------
    # Session
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
        if self._scheduled_reboot_cancel is not None:
            self._scheduled_reboot_cancel()
            self._scheduled_reboot_cancel = None
        if self._session and not self._session.closed:
            await self._session.close()

    def _setup_scheduled_reboot(self, entry: ConfigEntry) -> None:
        """Register a daily time-based reboot if enabled in options."""
        if not entry.options.get(CONF_SCHEDULED_REBOOT, True):
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

    @property
    def init_complete(self) -> bool:
        """True once all four init ticks have completed."""
        return self._init_step >= 4

    # ------------------------------------------------------------------
    # Low-level API helpers
    # ------------------------------------------------------------------

    async def _async_get_config_raw(self, keys: list[str]) -> dict[str, Any]:
        """POST / — read config values for a single batch of keys."""
        session = self._get_session()
        body = msgpack.packb(keys, use_bin_type=True)
        async with self._request_lock:
            async with session.post(
                f"{self.base_url}/",
                data=body,
                headers={"Content-Type": "application/x-msgpack"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                return cast(
                    dict[str, Any], msgpack.unpackb(await resp.read(), raw=False)
                )

    def _chunk_config_keys(
        self, keys: list[str], max_body_bytes: int | None = None
    ) -> list[list[str]]:
        """Split config key reads into msgpack bodies no larger than max_body_bytes.

        The limit applies to the msgpack request body only, not HTTP headers.
        If a single key exceeds the limit by itself, it is sent alone so the
        caller can still attempt the request instead of failing locally.
        """
        if not keys:
            return []

        limit = max_body_bytes or self._MAX_CONFIG_REQUEST_BODY_BYTES
        chunks: list[list[str]] = []
        current: list[str] = []

        for key in keys:
            trial = current + [key]
            if current and len(msgpack.packb(trial, use_bin_type=True)) > limit:
                chunks.append(current)
                current = [key]
            else:
                current = trial

        if current:
            chunks.append(current)

        return chunks

    async def async_get_config(self, keys: list[str]) -> dict[str, Any]:
        """POST / — read config values, chunking by msgpack body size.

        The WizFi360 delivers incoming TCP data via AT+IPD events.  When the
        request body exceeds the module's buffer (~500–600 bytes this is a best
        guess) the payload is split across two AT+IPD events and the MCU
        firmware misparses the second chunk as additional msgpack array
        elements, causing '!!! element N is not msgpack str' errors and
        eventual watchdog resets. Keeping each msgpack body at or below
        _MAX_CONFIG_REQUEST_BODY_BYTES stays safely inside one AT+IPD delivery.
        """
        result: dict[str, Any] = {}
        for chunk in self._chunk_config_keys(keys):
            result.update(await self._async_get_config_raw(chunk))
        return result

    async def async_set_config(self, params: dict[str, Any]) -> None:
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
        async with self._request_lock:
            async with session.put(
                f"{self.base_url}/",
                data=body,
                headers={"Content-Type": "application/x-msgpack"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()

    async def async_get_state(self) -> dict[str, Any]:
        """GET /state — returns PWM values, sensor readings, uptime, etc."""
        session = self._get_session()
        async with self._request_lock:
            async with session.get(
                f"{self.base_url}/state",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                return cast(
                    dict[str, Any], msgpack.unpackb(await resp.read(), raw=False)
                )

    async def async_get_weather(self) -> list[Any]:
        """GET /weather — returns per-channel weather simulation state.

        The response is a msgpack stream whose first object is a list with one
        entry per PWM channel.  Each entry is either None (no weather program
        assigned) or a dict with keys such as weather_program_id, clouds_state,
        cloudticks, clouds_next_state_tick, rainfront_start, rainfront_length,
        rainmins, rain_next_tick, moon_state, moon_next_state_tick.
        """
        session = self._get_session()
        async with self._request_lock:
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
        async with self._request_lock:
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
        async with self._request_lock:
            async with session.put(
                f"{self.base_url}/state",
                data=body,
                headers={"Content-Type": "application/x-msgpack"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()

    async def async_set_dst_auto_track(self, enabled: bool) -> None:
        """Enable or disable automatic DST tracking.

        User-initiated: fires a PUT / immediately to sync summertime so the
        device is correct the moment the switch is turned on.  Poll-detected
        transitions are handled via _dst_sync_pending (replaces one tick).
        """
        self._dst_auto_track = enabled
        if enabled:
            is_dst = bool(dt_util.now().dst())
            self._last_known_dst = is_dst
            await self.async_set_config({"summertime": 1 if is_dst else 0})
            self.config["summertime"] = 1 if is_dst else 0

    def _check_dst_changed(self) -> None:
        """After each successful poll tick, check whether DST has transitioned.

        No HTTP request — pure Python.  Sets _dst_sync_pending so the *next*
        tick becomes a dedicated PUT / instead of state or weather.  This keeps
        every tick to exactly one request.
        """
        if not self._dst_auto_track:
            return
        is_dst = bool(dt_util.now().dst())
        if is_dst != self._last_known_dst:
            self._dst_sync_pending = True

    async def _async_do_dst_sync(self) -> dict[str, Any]:
        """Execute the pending DST sync — replaces one poll tick entirely."""
        is_dst = bool(dt_util.now().dst())
        self._last_known_dst = is_dst
        try:
            await self.async_set_config({"summertime": 1 if is_dst else 0})
            self.config["summertime"] = 1 if is_dst else 0
        except aiohttp.ClientError as err:
            _LOGGER.warning("Could not sync DST to device: %s", err)
            self._dst_sync_pending = True  # retry next tick
        return dict(self.data or {})

    async def async_set_pwms(self, pwm_values: dict[str, int]) -> None:
        """PUT /state — set PWM channels immediately.

        Values are 0–1000. Note: if a program is running, it will resume
        control after ~1 minute. Use async_set_config with dayplanner keys
        for persistent changes.
        """
        session = self._get_session()
        body = msgpack.packb({"pwms": pwm_values}, use_bin_type=True)
        async with self._request_lock:
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
            async with self._request_lock:
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
        async with self._request_lock:
            async with session.get(
                f"{self.base_url}/reboot",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()

    async def async_get_factory_backup(self) -> bytes:
        """GET /factorybackup — download the factory default configuration as msgpack bytes."""
        session = self._get_session()
        async with self._request_lock:
            async with session.get(
                f"{self.base_url}/factorybackup",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def async_get_firmware(self) -> bytes:
        """GET /firmware.mp — download firmware info as msgpack bytes."""
        session = self._get_session()
        async with self._request_lock:
            async with session.get(
                f"{self.base_url}/firmware.mp",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def async_get_bootload(self) -> bytes:
        """GET /bootload.mp — download bootloader info as msgpack bytes."""
        session = self._get_session()
        async with self._request_lock:
            async with session.get(
                f"{self.base_url}/bootload.mp",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def async_factory_reset(self) -> None:
        """DELETE / — reset all device configuration to factory defaults."""
        session = self._get_session()
        async with self._request_lock:
            async with session.delete(
                f"{self.base_url}/",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()

    async def async_get_backup(self) -> bytes:
        """GET /backup — download complete device configuration as msgpack bytes."""
        session = self._get_session()
        async with self._request_lock:
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
        async with self._request_lock:
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
        async with self._request_lock:
            async with session.get(
                f"{self.base_url}/errors",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                return await resp.text()

    async def async_get_log(self) -> str:
        """GET /log — retrieve the device diagnostic log."""
        session = self._get_session()
        async with self._request_lock:
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
        flat = self.config.get(f"dayplanner#marker#{pwm}") or []
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
        self.config[f"dayplanner#marker#{pwm}"] = flat

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
        """No-op — all config is loaded lazily by the poll loop.

        Steps 0-3 of the init state machine each make exactly one HTTP request so
        the WizFi360 module has a full poll interval to tear down the TCP session
        before the next connection arrives.
        """

    async def _async_init_base_config(self) -> dict[str, Any]:
        """Init tick 0 — fetch name, model, pwm_count, etc."""
        base = await self.async_get_config(self._BASE_CONFIG_KEYS)
        self.config.update(base)
        self._init_step = 1
        return {}

    async def _async_init_state(self) -> dict[str, Any]:
        """Init tick 1 — fetch /state; derive pwm_count and discover sensor ROMs."""
        state = await self.async_get_state()
        pwm_count = self.config.get("pwm_count") or len(state.get("pwms", {})) or 8
        self.config["pwm_count"] = pwm_count
        self._pending_sensor_roms = [
            rom
            for rom in state.get("sensors", {})
            if f"sensors#sensor#{rom}#name" not in self.config
        ]
        self._last_state_refresh_succeeded = True
        self._consecutive_failures = 0
        self._init_step = 2
        data = dict(state)
        data["ok"] = True
        data.setdefault("weather", [])
        return data

    async def _async_init_pwm_config(self) -> dict[str, Any]:
        """Init tick 2 — fetch PWM config and any sensor config, one chunk per tick.

        On the first call builds the key list and queues all chunks into
        _pending_refresh_chunks.  Each subsequent call (still at _init_step == 2)
        drains one chunk.  When the final chunk is applied, advances _init_step to 3.

        This preserves the one-request-per-tick contract: the WizFi360 TCP stack
        needs a full scan interval to tear down one TCP session before the next
        connection arrives.  Sending all chunks back-to-back in a tight loop
        triggers WizFi360 AT+IPD corruption and eventual watchdog resets.
        """
        if not self._pending_refresh_chunks:
            # First call — build key list and stage all chunks.
            pwm_count = self.config.get("pwm_count") or 8
            keys: list[str] = []
            for i in range(1, pwm_count + 1):
                keys += [
                    f"pwm#{i}#name",
                    f"pwm#{i}#onoff",
                    f"pwm#{i}#max",
                    f"pwm#{i}#color",
                    f"pwm#{i}#manager",
                    f"pwm#{i}#fixed",
                    f"dayplanner#marker#{i}",
                ]
            for rom in self._pending_sensor_roms:
                keys += [
                    f"sensors#sensor#{rom}#name",
                    f"sensors#sensor#{rom}#unit",
                    f"sensors#sensor#{rom}#unitcomma",
                ]
            self._pending_refresh_chunks = self._chunk_config_keys(keys)
            self._refresh_accumulator = {}

        chunk = self._pending_refresh_chunks.pop(0)
        fresh = await self._async_get_config_raw(chunk)
        self._refresh_accumulator.update(fresh)

        if self._pending_refresh_chunks:
            # More chunks queued — stay at init_step 2 until all are done.
            return dict(self.data) if self.data else {}

        # Final chunk — apply accumulated config and advance.
        self.config.update(self._refresh_accumulator)
        self._refresh_accumulator = {}
        self._init_step = 3
        return dict(self.data) if self.data else {}

    async def _async_init_weather(self) -> dict[str, Any]:
        """Init tick 3 — fetch /weather so weather sensor entities can be created.

        Failure is graceful: an empty weather list is returned so the rest of
        init still completes and entities are set up.
        """
        data = dict(self.data) if self.data else {}
        try:
            data["weather"] = await self.async_get_weather()
        except (aiohttp.ClientError, Exception) as err:
            _LOGGER.debug("Could not fetch initial weather data: %s", err)
            data.setdefault("weather", [])
        self._init_step = 4
        self._next_refresh_index = 0
        return data

    # ------------------------------------------------------------------
    # Coordinator update
    # ------------------------------------------------------------------

    _FAILURE_GRACE = 3

    def _enqueue_pwm_refresh(self) -> None:
        """Build the PWM config key list and queue it as per-tick chunks.

        Fetches pwm#X#color for every channel (activation detection) plus the
        four detail keys only for currently-active channels.  Also drains
        _pending_config_keys (new sensor ROMs, weather program names).

        The full list is split into msgpack bodies no larger than
        _MAX_CONFIG_REQUEST_BODY_BYTES; _async_update_data drains one chunk per
        tick so the one-request-per-tick contract is preserved even when the
        key list is too large for a single AT+IPD delivery.
        """
        pwm_count = self.config.get("pwm_count") or 8
        keys: list[str] = []
        for i in range(1, pwm_count + 1):
            keys.append(f"pwm#{i}#color")
        for i in range(1, pwm_count + 1):
            if not self.pwm_is_unused(i):
                keys += [
                    f"pwm#{i}#onoff",
                    f"pwm#{i}#name",
                    f"pwm#{i}#manager",
                    f"pwm#{i}#fixed",
                ]
        pending = list(self._pending_config_keys)
        self._pending_config_keys.difference_update(pending)
        keys += pending
        self._pending_refresh_chunks = self._chunk_config_keys(keys)
        self._refresh_accumulator = {}

    async def _async_drain_one_refresh_chunk(self) -> dict[str, Any]:
        """Send the next queued PWM config chunk — one HTTP request, one tick.

        Returns the unchanged data object (suppressing listener notification)
        while chunks remain.  On the final chunk applies the accumulated config
        and returns new data so listeners are notified only if something changed.
        """
        chunk = self._pending_refresh_chunks.pop(0)
        try:
            fresh = await self._async_get_config_raw(chunk)
            self._refresh_accumulator.update(fresh)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not refresh PWM config: %s", err)
            self._pending_refresh_chunks.clear()
            self._refresh_accumulator.clear()
            return self.data or {}

        if self._pending_refresh_chunks:
            # More chunks still queued — hold off notifying listeners.
            return self.data or {}

        # Final chunk — apply accumulated results and signal if anything changed.
        fresh = self._refresh_accumulator
        self._refresh_accumulator = {}
        changed = any(self.config.get(k) != v for k, v in fresh.items())
        self.config.update(fresh)
        data = dict(self.data or {})
        data["ok"] = self._last_state_refresh_succeeded
        return data if changed else (self.data or data)

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
                return self.data
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
                    "device_unreachable",
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
            async_delete_issue(self.hass, DOMAIN, "device_unreachable")
            # Reset the PWM config refresh counter so it doesn't fire
            # immediately on the first tick back — a freshly booted device
            # needs time to stabilise before it can handle a large batch.
            self._ticks_since_pwm_refresh = 0
        self._consecutive_failures = 0
        self._last_state_refresh_succeeded = True
        data = dict(self.data or {})
        data["timewarp"] = 0  # reset before merge; device omits the key when inactive
        data.update(state)

        # Queue config keys for any sensors that have appeared since last update.
        # Fetching here would make a second request in the same tick; instead we
        # drain the queue on the next pwm_config tick alongside the PWM keys.
        if state.get("sensors"):
            for rom in state["sensors"]:
                if f"sensors#sensor#{rom}#name" not in self.config:
                    self._pending_config_keys.update(
                        [
                            f"sensors#sensor#{rom}#name",
                            f"sensors#sensor#{rom}#unit",
                            f"sensors#sensor#{rom}#unitcomma",
                        ]
                    )

        return data

    async def _async_refresh_weather(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            weather = await self.async_get_weather()
            data["weather"] = weather

            # Queue names for any weather program IDs we haven't seen before.
            # Fetching here would make a second request in the same tick; drained
            # on the next pwm_config tick instead.
            for ch in weather:
                if ch is not None and ch.get("weather_program_id") is not None:
                    pid = ch["weather_program_id"]
                    if f"weather#setup#{pid}#name" not in self.config:
                        self._pending_config_keys.add(f"weather#setup#{pid}#name")
        except aiohttp.ClientError as err:
            _LOGGER.debug("Could not fetch weather data: %s", err)
            data.setdefault("weather", [])
        except Exception as err:
            _LOGGER.debug("Unexpected error fetching weather data: %s", err)
            data.setdefault("weather", [])

        return data

    async def _async_update_data(self) -> dict[str, Any]:
        # ── Init phase: steps 0–2 retry on failure; step 3 always completes ──
        if 0 <= self._init_step <= 2:
            try:
                if self._init_step == 0:
                    return await self._async_init_base_config()
                if self._init_step == 1:
                    return await self._async_init_state()
                return await self._async_init_pwm_config()
            except (aiohttp.ClientError, Exception) as err:
                raise UpdateFailed(
                    f"Error communicating with SunRiser at {self.host}: {err}"
                ) from err

        if self._init_step == 3:
            return await self._async_init_weather()

        # ── Pending DST sync — replaces one tick, keeps 1 request/tick ──────────
        if self._dst_sync_pending:
            self._dst_sync_pending = False
            return await self._async_do_dst_sync()

        # ── Normal round-robin ──────────────────────────────────────────────────
        # Every _PWM_CONFIG_INTERVAL ticks enqueue a PWM config refresh.
        # _enqueue_pwm_refresh splits the key list into byte-sized chunks;
        # _async_drain_one_refresh_chunk sends exactly one chunk per tick so the
        # one-request-per-tick contract is never broken.
        self._ticks_since_pwm_refresh += 1
        if self._ticks_since_pwm_refresh >= self._PWM_CONFIG_INTERVAL:
            self._ticks_since_pwm_refresh = 0
            self._enqueue_pwm_refresh()

        if self._pending_refresh_chunks:
            return await self._async_drain_one_refresh_chunk()

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
        self._check_dst_changed()
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
