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

HOST = "192.168.0.13"
PORT = 80
BASE_URL = f"http://{HOST}:{PORT}"
TIMEOUT = aiohttp.ClientTimeout(total=10)

# Keys to read during the config test
CONFIG_KEYS = ["name", "model", "model_id", "pwm_count", "hostname", "factory_version", "save_version"]


@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
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


# ---------------------------------------------------------------------------
# PWM config read (uses pwm_count from config)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_pwm_config(session):
    """Read per-channel config for all PWMs."""
    # First get pwm_count
    body = msgpack.packb(["pwm_count"], use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        base = msgpack.unpackb(await resp.read(), raw=False)

    pwm_count = base.get("pwm_count") or 8
    print(f"\npwm_count: {pwm_count}")

    pwm_keys = []
    for i in range(1, pwm_count + 1):
        pwm_keys += [f"pwm#{i}#name", f"pwm#{i}#onoff", f"pwm#{i}#max"]

    body = msgpack.packb(pwm_keys, use_bin_type=True)
    async with session.post(
        f"{BASE_URL}/",
        data=body,
        headers={"Content-Type": "application/x-msgpack"},
        timeout=TIMEOUT,
    ) as resp:
        assert resp.status == 200
        result = msgpack.unpackb(await resp.read(), raw=False)
        print("PWM config:")
        for k, v in result.items():
            print(f"  {k}: {v!r}")


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
