"""Used API of aioresponses 0.7.8; fixes unparameterized Pattern and requests.

Keep in sync with aioresponses/core.py when upgrading the test dependency.
"""

from re import Pattern
from types import TracebackType
from typing import Any, NamedTuple, Self
from yarl import URL

class RequestCall(NamedTuple):
    args: tuple[Any, ...]
    kwargs: dict[str, Any]

class aioresponses:
    requests: dict[tuple[str, URL], list[RequestCall]]
    def __init__(self, **kwargs: Any) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
    def get(self, url: URL | str | Pattern[str], **kwargs: Any) -> None: ...
    def post(self, url: URL | str | Pattern[str], **kwargs: Any) -> None: ...
    def put(self, url: URL | str | Pattern[str], **kwargs: Any) -> None: ...
    def delete(self, url: URL | str | Pattern[str], **kwargs: Any) -> None: ...
