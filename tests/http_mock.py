# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller HTTP mock on top of Home Assistant's AiohttpClientMocker.

Home Assistant's mocker supplies the mocked session and responses, so the
tests follow the aiohttp version Home Assistant ships. This adapter adds what
the controller tests rely on:

- each registered reply is used once, and replies for the same request are
  served in the order they were registered;
- a request with no reply left fails like an unreachable controller
  (``aiohttp.ClientConnectionError``);
- ``requests`` records what was sent, keyed by ``(METHOD, URL)``.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import aiohttp
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.sunriser.coordinator import SunRiserCoordinator


@dataclass(frozen=True)
class SentRequest:
    """The body of one request the integration sent."""

    data: Any


@dataclass(frozen=True)
class _Reply:
    status: int
    body: bytes
    headers: dict[str, str] | None
    exception: BaseException | None


class ControllerHttp:
    """Registered controller replies and the requests that consumed them."""

    def __init__(self) -> None:
        self._replies: defaultdict[tuple[str, URL], deque[_Reply]] = defaultdict(deque)
        self.requests: defaultdict[tuple[str, URL], list[SentRequest]] = defaultdict(
            list
        )

    def _add(
        self,
        method: str,
        url: str,
        body: bytes | str,
        status: int,
        headers: dict[str, str] | None,
        exception: BaseException | None,
    ) -> None:
        raw = body.encode() if isinstance(body, str) else body
        self._replies[(method, URL(url))].append(
            _Reply(status, raw, headers, exception)
        )

    def get(
        self,
        url: str,
        *,
        body: bytes | str = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self._add("GET", url, body, status, headers, exception)

    def put(
        self,
        url: str,
        *,
        body: bytes | str = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self._add("PUT", url, body, status, headers, exception)

    def post(
        self,
        url: str,
        *,
        body: bytes | str = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self._add("POST", url, body, status, headers, exception)

    def delete(
        self,
        url: str,
        *,
        body: bytes | str = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self._add("DELETE", url, body, status, headers, exception)

    async def _answer(self, method: str, url: URL, data: Any) -> Any:
        key = (method.upper(), url)
        self.requests[key].append(SentRequest(data))
        queue = self._replies.get(key)
        if not queue:
            raise aiohttp.ClientConnectionError(f"Connection refused: {method} {url}")
        reply = queue.popleft()
        if reply.exception is not None:
            raise reply.exception
        return AiohttpClientMockResponse(
            method,
            url,
            status=HTTPStatus(reply.status),
            response=reply.body,
            headers=reply.headers,
        )


# One mocked session answers from the innermost active block, so a coordinator
# that keeps its session across blocks still reaches the current replies.
_ACTIVE: list[ControllerHttp] = []
_MOCKER = AiohttpClientMocker()


async def _dispatch(method: str, url: URL, data: Any) -> Any:
    if not _ACTIVE:
        raise AssertionError(f"Controller request outside controller_http(): {url}")
    return await _ACTIVE[-1]._answer(method, url, data)


for _method in ("get", "put", "post", "delete"):
    _MOCKER.request(  # pyright: ignore[reportUnknownMemberType]  # Untyped HA test helper.
        _method, re.compile(".*"), side_effect=_dispatch
    )


def _mocked_session(_coordinator: SunRiserCoordinator) -> aiohttp.ClientSession:
    return _MOCKER.create_session(  # pyright: ignore[reportUnknownMemberType]  # Untyped HA test helper.
        None
    )


@contextmanager
def controller_http() -> Generator[ControllerHttp]:
    """Answer controller requests made inside the block from registered replies."""
    http = ControllerHttp()
    _ACTIVE.append(http)
    try:
        with patch.object(SunRiserCoordinator, "_create_session", _mocked_session):
            yield http
    finally:
        _ACTIVE.remove(http)
