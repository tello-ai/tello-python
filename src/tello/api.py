"""Client for the Tello public REST API (``/v1``): tools, agents, crews,
crew generation and call drafts.

Separate from the WebSocket :class:`tello.TelloClient`. Requests and
responses are plain JSON objects (``dict[str, Any]``), so fields this SDK does
not know yet are kept. Writes take effect at once: the next call uses them.
Nothing is retried automatically.

    import asyncio
    from tello import TelloApi

    async def main():
        api = TelloApi(api_key="tello_live_xxx")
        agents = await api.agents.list()
        print([a["name"] for a in agents["data"]])

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from typing import Any

from ._version import __version__
from .config import DEFAULT_API_URL, ENV_API_KEY, ENV_API_URL
from .errors import TelloApiConnectionError, TelloApiError

#: Default request timeout in seconds.
DEFAULT_TIMEOUT = 30.0
#: Timeout for requests the service may take long to finish
#: (``crews.generate``, ``call_drafts.create``/``revise``/``confirm``).
DEFAULT_LONG_TIMEOUT = 120.0

_USER_AGENT = f"tello-python-sdk/{__version__}"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_MAX_BODY = 8 << 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report a redirect as the error response it is: never resend the key."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _resolve_api_url(api_url: str | None) -> str:
    url = (api_url or os.environ.get(ENV_API_URL) or DEFAULT_API_URL).rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return url
    raise ValueError(
        "api_url must be an https:// URL (http:// only for 127.0.0.1, localhost or ::1)"
    )


class _Transport:
    def __init__(self, api_key: str, api_url: str, timeout: float, long_timeout: float) -> None:
        self._key = api_key
        self.api_url = api_url
        self.timeout = timeout
        self.long_timeout = long_timeout
        self._opener = urllib.request.build_opener(_NoRedirect())

    async def request(
        self,
        method: str,
        path: str,
        *,
        expect: tuple[int, ...],
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        url = self.api_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        req = urllib.request.Request(url, method=method, headers=headers)
        status, raw = await asyncio.to_thread(self._send, req, method, path, self.timeout)
        return self._result(status, raw, expect)

    def _send(
        self, req: urllib.request.Request, method: str, path: str, timeout: float
    ) -> tuple[int, bytes]:
        try:
            try:
                with self._opener.open(req, timeout=timeout) as resp:
                    return resp.status, resp.read(_MAX_BODY)
            except urllib.error.HTTPError as exc:
                with exc:
                    return exc.code, exc.read(_MAX_BODY)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            raise TelloApiConnectionError(f"{method} {path} failed: {reason}") from exc

    @staticmethod
    def _result(status: int, raw: bytes, expect: tuple[int, ...]) -> dict[str, Any] | None:
        if not 200 <= status <= 299:
            raise _api_error(status, raw)
        if status not in expect:
            raise TelloApiError(status, "invalid_response", f"unexpected HTTP status {status}")
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise TelloApiError(status, "invalid_response", "response is not a JSON object")
        return body


def _api_error(status: int, raw: bytes) -> TelloApiError:
    try:
        env = json.loads(raw)
    except ValueError:
        env = None
    if isinstance(env, dict) and isinstance(env.get("error"), str) and env["error"]:
        code = env["error"]
        message = env.get("message")
        data = env.get("data")
        return TelloApiError(
            status,
            code,
            message if isinstance(message, str) and message else code,
            data if isinstance(data, dict) else None,
        )
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = f"HTTP {status}"
    return TelloApiError(status, f"http_{status}", phrase)


class AgentsApi:
    """``/agents``: portal agents."""

    def __init__(self, transport: _Transport) -> None:
        self._t = transport

    async def list(self) -> dict[str, Any]:
        """``GET /agents`` → ``{"data": [{"id", "name", "description", "isDefault"}]}``."""
        return await self._t.request("GET", "/agents", expect=(200,))  # type: ignore[return-value]


class TelloApi:
    """Client for the Tello public REST API.

    ``api_key`` falls back to ``TELLO_API_KEY``; ``api_url`` to
    ``TELLO_API_URL``, then ``https://api.telloai.io/v1``. Only ``https``
    URLs are accepted (``http`` only for loopback hosts, for tests).
    ``timeout`` bounds each request in seconds; ``long_timeout`` replaces it
    for ``crews.generate`` and ``call_drafts`` requests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        long_timeout: float = DEFAULT_LONG_TIMEOUT,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
        if not key:
            raise ValueError(f"api_key is required (pass api_key=... or set ${ENV_API_KEY})")
        self._transport = _Transport(key, _resolve_api_url(api_url), timeout, long_timeout)
        self.agents = AgentsApi(self._transport)

    @property
    def api_url(self) -> str:
        """The base URL requests go to, without a trailing slash."""
        return self._transport.api_url

    def __repr__(self) -> str:
        return f"TelloApi(api_url={self.api_url!r})"
