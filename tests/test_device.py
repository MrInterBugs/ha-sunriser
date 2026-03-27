"""
Standalone integration tests against a real SunRiser device.

Run with:
    pip install aiohttp msgpack pytest pytest-asyncio
    pytest tests/test_device.py -v
"""

import asyncio

import pytest
import pytest_asyncio
import aiohttp
import msgpack
import pytest_socket

import os

# Override with env vars to target the Docker simulator:
#   SUNRISER_HOST=127.0.0.1 SUNRISER_PORT=9000 pytest tests/test_device.py -v -s
HOST = os.environ.get("SUNRISER_HOST", "192.168.0.13")
PORT = int(os.environ.get("SUNRISER_PORT", "80"))
BASE_URL = f"http://{HOST}:{PORT}"
TIMEOUT = aiohttp.ClientTimeout(total=10)

# Allow real network connections for this file — pytest-socket (bundled with
# pytest-homeassistant-custom-component) blocks sockets by default.

# Keys to read during the config test
CONFIG_KEYS = [
    "name",
    "model",
    "model_id",
    "pwm_count",
    "hostname",
    "factory_version",
    "save_version",
]


@pytest_asyncio.fixture(autouse=True)
async def inter_test_delay():
    """2-second pause after every test to let the WizFi360 fully tear down the TCP session."""
    yield
    await asyncio.sleep(2)


@pytest_asyncio.fixture
async def session(socket_enabled):
    # pytest-homeassistant-custom-component keeps a host allowlist active even
    # when sockets are enabled, so standalone LAN tests must opt the target host
    # in explicitly.
    pytest_socket.socket_allow_hosts([HOST, "127.0.0.1", "localhost"])
    # force_close=True because the device closes the TCP connection after each
    # response without sending Connection: close — aiohttp would otherwise try
    # to reuse the socket and get a ConnectionResetError on the next request.
    connector = aiohttp.TCPConnector(force_close=True)
    async with aiohttp.ClientSession(connector=connector) as s:
        yield s


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping(session):
    """GET /ok should return the text OK.

    Retries once — the device occasionally resets the TCP connection on the
    very first request of a test run (cold-connection quirk).
    """
    for attempt in range(2):
        try:
            async with session.get(f"{BASE_URL}/ok", timeout=TIMEOUT) as resp:
                assert resp.status == 200, f"Expected 200, got {resp.status}"
                text = await resp.text()
                assert text.strip() == "OK", f"Expected 'OK', got {text!r}"
            return
        except aiohttp.ClientOSError:
            if attempt == 1:
                raise


# ---------------------------------------------------------------------------
# Config read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_config(session):
    """POST / with a msgpack array of keys should return a msgpack hash."""
    body = msgpack.packb(CONFIG_KEYS, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        print("\nConfig response:")
        for k, v in result.items():
            print(f"  {k}: {v!r}")
        assert "pwm_count" in result, "pwm_count missing from config response"
        assert (
            "save_version" in result
        ), "save_version missing (used for firmware version sensor)"
        assert "hostname" in result, "hostname missing (used for hostname sensor)"


# ---------------------------------------------------------------------------
# State read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_state(session):
    """GET /state should return a msgpack hash with a pwms key."""
    async with session.get(f"{BASE_URL}/state", timeout=TIMEOUT) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        print("\nState response:")
        for k, v in result.items():
            print(f"  {k}: {v!r}")
        assert "pwms" in result, "pwms key missing from state response"
        assert "uptime" in result, "uptime missing from state (used for uptime sensor)"


# ---------------------------------------------------------------------------
# PWM config read (uses pwm_count from config)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_pwm_config(session):
    """Read name, color, onoff, and max for all PWM channels in a single request.

    We request up to 10 channels (the max for SunRiser 10) to avoid needing
    a separate pwm_count lookup which would require a second TCP connection.
    """
    pwm_keys = ["pwm_count"]
    for i in range(1, 11):
        pwm_keys += [
            f"pwm#{i}#name",
            f"pwm#{i}#color",
            f"pwm#{i}#onoff",
            f"pwm#{i}#max",
        ]

    body = msgpack.packb(pwm_keys, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        assert resp.status == 200
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)

    pwm_count = result.get("pwm_count") or 10
    print(f"\npwm_count: {pwm_count}")
    for i in range(1, pwm_count + 1):
        name = result.get(f"pwm#{i}#name")
        color = result.get(f"pwm#{i}#color")
        onoff = result.get(f"pwm#{i}#onoff")
        print(f"  pwm#{i}: name={name!r}  color={color!r}  onoff={onoff!r}")


# ---------------------------------------------------------------------------
# PWM manager read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_pwm_manager(session):
    """Read pwm#X#manager for all channels and verify values are 0–3 or None."""
    keys = ["pwm_count"] + [f"pwm#{i}#manager" for i in range(1, 11)]
    body = msgpack.packb(keys, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)

    pwm_count = result.get("pwm_count") or 10
    _MANAGER_NAMES = {0: "none", 1: "dayplanner", 2: "weekplanner", 3: "celestial"}
    print(f"\npwm#X#manager values ({pwm_count} channels):")
    for i in range(1, pwm_count + 1):
        val = result.get(f"pwm#{i}#manager")
        assert (
            val is None or val in _MANAGER_NAMES
        ), f"pwm#{i}#manager={val!r} is not a valid manager id (expected 0–3 or None)"
        label = _MANAGER_NAMES.get(val or 0, "none")
        print(f"  pwm#{i}: manager={val!r} ({label})")


# ---------------------------------------------------------------------------
# Dayplanner read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_dayplanner(session):
    """Read dayplanner#marker#X for all PWM channels and verify the format.

    Each value should be either None (no schedule) or a flat list of
    alternating [daymin, percent, ...] pairs.
    """
    keys = [f"dayplanner#marker#{i}" for i in range(1, 11)]
    body = msgpack.packb(keys, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    print("\nDayplanner schedules:")
    for i in range(1, 11):
        key = f"dayplanner#marker#{i}"
        flat = result.get(key)
        if flat is None:
            print(f"  pwm#{i}: no schedule")
            continue
        assert isinstance(
            flat, list
        ), f"pwm#{i}: expected list, got {type(flat)}: {flat!r}"
        assert len(flat) % 2 == 0, f"pwm#{i}: flat list length {len(flat)} is not even"
        markers = []
        for j in range(0, len(flat), 2):
            daymin = int(flat[j])
            percent = int(flat[j + 1])
            assert 0 <= daymin <= 1439, f"pwm#{i}: daymin {daymin} out of range"
            assert 0 <= percent <= 100, f"pwm#{i}: percent {percent} out of range"
            markers.append(f"{daymin // 60:02d}:{daymin % 60:02d}={percent}%")
        print(f"  pwm#{i}: {', '.join(markers)}")


# ---------------------------------------------------------------------------
# Week planner read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_weekplanner(session):
    """Read weekplanner#programs#X for all PWM channels and verify the format.

    Each value should be either None (no schedule set) or a list of exactly 8
    integers: [sunday, monday, tuesday, wednesday, thursday, friday, saturday, default].
    """
    keys = [f"weekplanner#programs#{i}" for i in range(1, 11)]
    body = msgpack.packb(keys, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    _DAY_NAMES = [
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "default",
    ]
    print("\nWeek planner schedules:")
    for i in range(1, 11):
        key = f"weekplanner#programs#{i}"
        programs = result.get(key)
        if programs is None:
            print(f"  pwm#{i}: no week schedule")
            continue
        assert isinstance(
            programs, list
        ), f"pwm#{i}: expected list, got {type(programs)}: {programs!r}"
        assert (
            len(programs) == 8
        ), f"pwm#{i}: expected 8 entries, got {len(programs)}: {programs!r}"
        for j, prog_id in enumerate(programs):
            assert isinstance(
                prog_id, int
            ), f"pwm#{i}: programs[{j}] ({_DAY_NAMES[j]}) is not int: {prog_id!r}"
        day_map = dict(zip(_DAY_NAMES, programs))
        print(f"  pwm#{i}: {day_map}")


# ---------------------------------------------------------------------------
# Dayplanner + week planner write (real device only — always restores original)
# ---------------------------------------------------------------------------

_REAL_ONLY = pytest.mark.skipif(
    PORT == 9000,
    reason="Real device only — simulator does not persist config writes",
)


async def _read_config(session, keys: list) -> dict:
    await asyncio.sleep(2)
    body = msgpack.packb(keys, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        return msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)


async def _write_config(session, params: dict) -> None:
    await asyncio.sleep(2)
    body = msgpack.packb(params, use_bin_type=True)
    async with session.put(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        resp.raise_for_status()


@_REAL_ONLY
@pytest.mark.asyncio
async def test_write_dayplanner(session):
    """Write a test schedule to pwm#1, verify it, then restore the original.

    Uses pwm#1 — always restores via finally so the device is never left
    in a modified state even if an assertion fails.
    """
    TEST_PWM = 1
    marker_key = f"dayplanner#marker#{TEST_PWM}"

    # Step 1: capture current state + factory_version (needed for PUT /)
    result = await _read_config(session, [marker_key, "factory_version"])
    original_flat = result.get(marker_key)
    factory_version = result.get("factory_version")
    print(f"\nOriginal flat markers: {original_flat!r}")
    print(f"factory_version: {factory_version!r}")

    # Test schedule: two markers, clearly different from any real schedule
    test_flat = [720, 42, 900, 88]  # 12:00=42%, 15:00=88%

    try:
        # Step 2: write test schedule
        payload = {marker_key: test_flat}
        if factory_version:
            payload["save_version"] = factory_version
        await _write_config(session, payload)
        print(f"Wrote test markers: {test_flat!r}")

        # Step 3: read back and verify
        verify = await _read_config(session, [marker_key])
        written = verify.get(marker_key)
        print(f"Read back markers: {written!r}")
        assert (
            written == test_flat
        ), f"Round-trip mismatch: sent {test_flat!r}, got {written!r}"
        print("Round-trip OK")

    finally:
        # Step 4: always restore original
        restore_payload = {marker_key: original_flat}
        if factory_version:
            restore_payload["save_version"] = factory_version
        await _write_config(session, restore_payload)
        print(f"Restored original markers: {original_flat!r}")

        # The device reloads config after a PUT / and drops the TCP connection —
        # a 200 from the write is sufficient proof the restore succeeded.
        print("Restore write returned 200 — OK")


@_REAL_ONLY
@pytest.mark.asyncio
async def test_write_weekplanner(session):
    """Write a test week schedule to pwm#1, verify it, then restore the original.

    Uses pwm#1 regardless of its current manager setting — the key can be written
    independently of the manager. Always restores via finally.
    """
    TEST_PWM = 1
    programs_key = f"weekplanner#programs#{TEST_PWM}"

    result = await _read_config(session, [programs_key, "factory_version"])
    original = result.get(programs_key)
    factory_version = result.get("factory_version")
    print(f"\nOriginal {programs_key}: {original!r}")
    print(f"factory_version: {factory_version!r}")

    # Test schedule: program 7 on weekdays, program 8 on weekends, default=7
    test_flat = [8, 7, 7, 7, 7, 7, 8, 7]  # [sun, mon, tue, wed, thu, fri, sat, default]

    try:
        payload = {programs_key: test_flat}
        if factory_version:
            payload["save_version"] = factory_version
        await _write_config(session, payload)
        print(f"Wrote {programs_key}={test_flat!r}")

        verify = await _read_config(session, [programs_key])
        written = verify.get(programs_key)
        print(f"Read back: {written!r}")
        assert (
            written == test_flat
        ), f"Round-trip mismatch: sent {test_flat!r}, got {written!r}"
        print("Round-trip OK")

    finally:
        restore_payload = {programs_key: original}
        if factory_version:
            restore_payload["save_version"] = factory_version
        await _write_config(session, restore_payload)
        print(f"Restored {programs_key}={original!r}")


@_REAL_ONLY
@pytest.mark.asyncio
async def test_write_pwm_manager(session):
    """Write a different manager value to pwm#1, verify it, then restore the original.

    Uses pwm#1 — always restores via finally so the device is never left
    in a modified state even if an assertion fails.
    """
    TEST_PWM = 1
    manager_key = f"pwm#{TEST_PWM}#manager"

    result = await _read_config(session, [manager_key, "factory_version"])
    original = result.get(manager_key)
    factory_version = result.get("factory_version")
    print(f"\nOriginal {manager_key}: {original!r}")
    print(f"factory_version: {factory_version!r}")

    # Pick a test value that differs from the current one
    test_value = 1 if (original or 0) != 1 else 0

    try:
        payload = {manager_key: test_value}
        if factory_version:
            payload["save_version"] = factory_version
        await _write_config(session, payload)
        print(f"Wrote {manager_key}={test_value!r}")

        verify = await _read_config(session, [manager_key])
        written = verify.get(manager_key)
        print(f"Read back: {written!r}")
        assert (
            written == test_value
        ), f"Round-trip mismatch: sent {test_value!r}, got {written!r}"
        print("Round-trip OK")

    finally:
        restore_payload = {manager_key: original}
        if factory_version:
            restore_payload["save_version"] = factory_version
        await _write_config(session, restore_payload)
        print(f"Restored {manager_key}={original!r}")


# ---------------------------------------------------------------------------
# Maintenance mode
# ---------------------------------------------------------------------------


async def _put_state(session, payload: dict) -> tuple[int, dict | str]:
    """PUT /state helper — returns (status_code, decoded_body)."""
    body = msgpack.packb(payload, use_bin_type=True)
    async with session.put(
        f"{BASE_URL}/state",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        raw = await resp.read()
        try:
            decoded = msgpack.unpackb(raw, raw=False, strict_map_key=False)
        except Exception:
            decoded = raw.decode(errors="replace")
        return resp.status, decoded


async def _get_service_mode(session) -> object:
    async with session.get(f"{BASE_URL}/state", timeout=TIMEOUT) as resp:
        state = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)
    return state.get("service_mode")


@pytest.mark.asyncio
async def test_maintenance_mode_integer(session):
    """Enable maintenance mode with integer 1, disable with integer 0.

    The device initialises service_mode as integer 0 so it likely expects
    integers rather than msgpack booleans.
    """
    initial = await _get_service_mode(session)
    print(f"\nservice_mode before: {initial!r}")

    # Enable with integer 1
    await asyncio.sleep(2)
    status, body = await _put_state(session, {"service_mode": 1})
    print(f"PUT service_mode=1 → {status} {body!r}")
    assert status == 200, f"Enable failed with {status}: {body}"

    await asyncio.sleep(2)
    after_on = await _get_service_mode(session)
    print(f"service_mode after enable: {after_on!r}")
    if PORT == 9000 and not after_on:
        # The simulator's state() method returns a fresh dict on every call in
        # non-demo mode, so service_mode is never persisted between requests.
        pytest.skip(
            "Simulator non-demo mode does not persist service_mode between requests"
        )
    assert after_on, f"Expected truthy service_mode after enable, got {after_on!r}"

    # Disable with integer 0
    await asyncio.sleep(2)
    status, body = await _put_state(session, {"service_mode": 0})
    print(f"PUT service_mode=0 → {status} {body!r}")
    assert status == 200, f"Disable failed with {status}: {body}"

    await asyncio.sleep(2)
    after_off = await _get_service_mode(session)
    print(f"service_mode after disable: {after_off!r}")
    assert (
        not after_off
    ), f"Expected falsy service_mode after disable, got {after_off!r}"


@pytest.mark.asyncio
async def test_maintenance_mode_boolean(session):
    """Try enabling maintenance mode with msgpack boolean True.

    This may return 500 on real firmware — if so, use integers instead.
    """
    await asyncio.sleep(2)
    status, body = await _put_state(session, {"service_mode": True})
    print(f"\nPUT service_mode=True → {status} {body!r}")

    if status == 500:
        # Device resets the TCP connection after a 500, so the cleanup call may
        # also fail — ignore errors here and skip the test regardless.
        try:
            await asyncio.sleep(2)
            await _put_state(session, {"service_mode": 0})
        except Exception:
            pass
        pytest.skip(
            "Device returned 500 for boolean — use integers (see test_maintenance_mode_integer)"
        )

    assert status == 200

    # Clean up
    await asyncio.sleep(2)
    await _put_state(session, {"service_mode": 0})


# ---------------------------------------------------------------------------
# Sensor read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensors_in_state(session):
    """Check if any temperature sensors are reported in state."""
    async with session.get(f"{BASE_URL}/state", timeout=TIMEOUT) as resp:
        result = msgpack.unpackb(await resp.read(), raw=False, strict_map_key=False)

    sensors = result.get("sensors", {})
    if sensors:
        print(f"\nSensors found: {list(sensors.keys())}")
        for rom, data in sensors.items():
            print(f"  {rom}: device_type={data[0]}, raw_value={data[1]}")
    else:
        print("\nNo sensors present on device")


# ---------------------------------------------------------------------------
# Weather simulation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_weather(session):
    """GET /weather should return a msgpack stream whose first object is a list."""
    async with session.get(f"{BASE_URL}/weather", timeout=TIMEOUT) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        raw = await resp.read()

    unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
    unpacker.feed(raw)
    channels = next(iter(unpacker), None)

    assert isinstance(
        channels, list
    ), f"Expected list as first object, got {type(channels)}"
    print(f"\nWeather channels ({len(channels)} total):")
    for i, ch in enumerate(channels):
        print(f"  channel {i + 1}: {ch!r}")


@pytest.mark.asyncio
async def test_weather_channel_schema(session):
    """Active weather channels must contain the expected keys."""
    async with session.get(f"{BASE_URL}/weather", timeout=TIMEOUT) as resp:
        raw = await resp.read()

    unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
    unpacker.feed(raw)
    channels = next(iter(unpacker), None) or []

    active = [ch for ch in channels if ch is not None]
    if not active:
        pytest.skip("No active weather channels on device")

    # Keys required only for channels with full cloud/rain simulation.
    # Moon-only channels (e.g. simulator channel 8) legitimately omit these.
    cloud_rain_keys = {
        "clouds_state",
        "cloudticks",
        "clouds_next_state_tick",
        "rainfront_start",
        "rainfront_length",
        "rainmins",
        "rain_next_tick",
    }
    for i, ch in enumerate(active):
        assert isinstance(ch, dict), f"Channel {i} is not a dict: {ch!r}"
        assert "weather_program_id" in ch, f"Channel {i} missing weather_program_id"
        if "clouds_state" in ch:
            missing = cloud_rain_keys - ch.keys()
            assert not missing, f"Channel {i} missing cloud/rain keys: {missing}"
        print(f"\nChannel {i + 1} keys present: {sorted(ch.keys())}")


# ---------------------------------------------------------------------------
# Factory backup / firmware / bootload endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_factorybackup(session):
    """GET /factorybackup should return a msgpack dict of factory default config."""
    async with session.get(f"{BASE_URL}/factorybackup", timeout=TIMEOUT) as resp:
        if resp.status in (404, 500):
            pytest.skip(
                f"GET /factorybackup not available on this firmware ({resp.status})"
            )
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        raw = await resp.read()

    result = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result!r}"
    print(f"\nFactory backup: {len(result)} keys — {sorted(result.keys())[:10]}")


# ---------------------------------------------------------------------------
# Admin endpoints — SIMULATOR ONLY
#
# These tests only run when SUNRISER_PORT=9000 (the Docker simulator).
# They MUST NOT run against the real device because:
#   - /restore sends a full config payload and triggers a deep device restart
#   - /reboot restarts the device immediately
#
# Run with:
#   docker run --rm -p 9000:9000 sunriser-sim
#   SUNRISER_HOST=127.0.0.1 SUNRISER_PORT=9000 pytest tests/test_device.py -v -s
# ---------------------------------------------------------------------------

_SIM_ONLY = pytest.mark.skipif(
    PORT != 9000,
    reason="Simulator only — run with SUNRISER_HOST=127.0.0.1 SUNRISER_PORT=9000",
)


@_SIM_ONLY
@pytest.mark.asyncio
async def test_get_firmware_mp(session):
    """GET /firmware.mp should return a msgpack dict with firmware metadata.

    Simulator only — keep off the real device to avoid any risk of triggering
    an unintended firmware operation.
    """
    async with session.get(f"{BASE_URL}/firmware.mp", timeout=TIMEOUT) as resp:
        if resp.status == 404:
            pytest.skip("GET /firmware.mp not available on this simulator build")
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        raw = await resp.read()

    result = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result!r}"
    print(f"\nFirmware info keys: {sorted(result.keys())}")
    for k, v in result.items():
        print(f"  {k}: {v!r}")


@_SIM_ONLY
@pytest.mark.asyncio
async def test_get_bootload_mp(session):
    """GET /bootload.mp should return a msgpack payload (dict or list).

    Simulator only — keep off the real device to avoid any risk of triggering
    an unintended bootloader operation.
    """
    async with session.get(f"{BASE_URL}/bootload.mp", timeout=TIMEOUT) as resp:
        if resp.status == 404:
            pytest.skip("GET /bootload.mp not available on this simulator build")
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        raw = await resp.read()

    assert len(raw) > 0, "Expected non-empty response from /bootload.mp"
    result = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    print(f"\nBootload info type={type(result).__name__}: {result!r}")


@pytest.mark.asyncio
async def test_get_errors(session):
    """GET /errors should respond with 200, or 404 if the simulator has no log files."""
    async with session.get(f"{BASE_URL}/errors", timeout=TIMEOUT) as resp:
        if resp.status == 404:
            pytest.skip("GET /errors not implemented in this simulator build")
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        content = await resp.text()
        print(f"\nError log ({len(content)} chars): {content[:200]!r}")


@pytest.mark.asyncio
async def test_get_log(session):
    """GET /log should respond with 200, or 404 if the simulator has no logfiles."""
    async with session.get(f"{BASE_URL}/log", timeout=TIMEOUT) as resp:
        if resp.status == 404:
            pytest.skip("GET /log not implemented in this simulator build")
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        content = await resp.text()
        print(f"\nDiagnostic log ({len(content)} chars): {content[:200]!r}")


@_SIM_ONLY
@pytest.mark.asyncio
async def test_backup(session):
    """GET /backup should return a msgpack dict of all device config."""
    async with session.get(f"{BASE_URL}/backup", timeout=TIMEOUT) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        raw = await resp.read()

    result = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result!r}"
    # A fresh simulator has an empty config dir, so the backup may be an empty dict.
    # The real device will have keys like "name", "hostname", etc.
    print(f"\nBackup contains {len(result)} keys: {sorted(result.keys())[:10]}")


@_SIM_ONLY
@pytest.mark.asyncio
async def test_restore(session):
    """PUT /restore: round-trip a backup back to the device.

    Downloads the current config via GET /backup, then sends it straight back
    via PUT /restore. No config values change; this just verifies the endpoint
    accepts a valid msgpack payload and returns 200.

    WARNING: triggers a deep simulator restart — keep this second-to-last.
    NEVER RUN AGAINST THE REAL DEVICE.
    """
    async with session.get(f"{BASE_URL}/backup", timeout=TIMEOUT) as resp:
        assert resp.status == 200, f"Backup step failed: {resp.status}"
        backup_data = await resp.read()

    await asyncio.sleep(2)
    async with session.put(
        f"{BASE_URL}/restore",
        data=backup_data,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        print(f"\nPUT /restore → {resp.status}")
        assert resp.status == 200, f"Restore failed: {resp.status}"


@_SIM_ONLY
@pytest.mark.asyncio
async def test_reboot(session):
    """GET /reboot should return 200 and initiate a simulator restart.

    Intentionally last — the simulator restarts after this call so any test
    that follows in the same run would face a cold connection.
    NEVER RUN AGAINST THE REAL DEVICE.
    """
    async with session.get(f"{BASE_URL}/reboot", timeout=TIMEOUT) as resp:
        print(f"\nGET /reboot → {resp.status}")
        assert resp.status == 200, f"Expected 200, got {resp.status}"
