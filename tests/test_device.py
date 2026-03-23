"""
Standalone integration tests against a real SunRiser device.

Run with:
    pip install aiohttp msgpack pytest pytest-asyncio
    pytest tests/test_device.py -v
"""

import pytest
import pytest_asyncio
import aiohttp
import msgpack
import pytest_socket

import os

# Override with env vars to target the Docker simulator:
#   SUNRISER_HOST=127.0.0.1 SUNRISER_PORT=8080 pytest tests/test_device.py -v -s
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
    """GET /ok should return the text OK."""
    async with session.get(f"{BASE_URL}/ok", timeout=TIMEOUT) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        text = await resp.text()
        assert text.strip() == "OK", f"Expected 'OK', got {text!r}"


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
        result = msgpack.unpackb(await resp.read(), raw=False)
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
        result = msgpack.unpackb(await resp.read(), raw=False)
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
        result = msgpack.unpackb(await resp.read(), raw=False)

    pwm_count = result.get("pwm_count") or 10
    print(f"\npwm_count: {pwm_count}")
    for i in range(1, pwm_count + 1):
        name = result.get(f"pwm#{i}#name")
        color = result.get(f"pwm#{i}#color")
        onoff = result.get(f"pwm#{i}#onoff")
        print(f"  pwm#{i}: name={name!r}  color={color!r}  onoff={onoff!r}")


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
            decoded = msgpack.unpackb(raw, raw=False)
        except Exception:
            decoded = raw.decode(errors="replace")
        return resp.status, decoded


async def _get_service_mode(session) -> object:
    async with session.get(f"{BASE_URL}/state", timeout=TIMEOUT) as resp:
        state = msgpack.unpackb(await resp.read(), raw=False)
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
    status, body = await _put_state(session, {"service_mode": 1})
    print(f"PUT service_mode=1 → {status} {body!r}")
    assert status == 200, f"Enable failed with {status}: {body}"

    after_on = await _get_service_mode(session)
    print(f"service_mode after enable: {after_on!r}")
    assert after_on, f"Expected truthy service_mode after enable, got {after_on!r}"

    # Disable with integer 0
    status, body = await _put_state(session, {"service_mode": 0})
    print(f"PUT service_mode=0 → {status} {body!r}")
    assert status == 200, f"Disable failed with {status}: {body}"

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
    status, body = await _put_state(session, {"service_mode": True})
    print(f"\nPUT service_mode=True → {status} {body!r}")

    if status == 500:
        # Device resets the TCP connection after a 500, so the cleanup call may
        # also fail — ignore errors here and skip the test regardless.
        try:
            await _put_state(session, {"service_mode": 0})
        except Exception:
            pass
        pytest.skip(
            "Device returned 500 for boolean — use integers (see test_maintenance_mode_integer)"
        )

    assert status == 200

    # Clean up
    await _put_state(session, {"service_mode": 0})


# ---------------------------------------------------------------------------
# Sensor read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensors_in_state(session):
    """Check if any temperature sensors are reported in state."""
    async with session.get(f"{BASE_URL}/state", timeout=TIMEOUT) as resp:
        result = msgpack.unpackb(await resp.read(), raw=False)

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

    unpacker = msgpack.Unpacker(raw=False)
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

    unpacker = msgpack.Unpacker(raw=False)
    unpacker.feed(raw)
    channels = next(iter(unpacker), None) or []

    active = [ch for ch in channels if ch is not None]
    if not active:
        pytest.skip("No active weather channels on device")

    required_keys = {
        "weather_program_id",
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
        missing = required_keys - ch.keys()
        assert not missing, f"Channel {i} missing keys: {missing}"
        print(f"\nChannel {i + 1} keys present: {sorted(ch.keys())}")
