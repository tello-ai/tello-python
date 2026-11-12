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
import uuid
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
    def __init__(
        self, api_key: str, api_url: str, timeout: float, long_timeout: float
    ) -> None:
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
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        long: bool = False,
    ) -> dict[str, Any]:
        """Send one request; return the JSON object (``{}`` for ``204``).

        ``expect`` lists the success statuses the API documents for the
        method; any other ``2xx`` is ``invalid_response``.
        """
        if idempotency_key is not None:
            _check_idempotency_key(idempotency_key)
        url = self.api_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            # http.client writes header values as latin-1: this sends the
            # key's UTF-8 bytes unchanged.
            headers["Idempotency-Key"] = idempotency_key.encode().decode("latin-1")
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        timeout = self.long_timeout if long else self.timeout
        status, raw = await asyncio.to_thread(self._send, req, timeout, idempotency_key)
        return _result(status, raw, expect, idempotency_key)

    def _send(
        self, req: urllib.request.Request, timeout: float, idempotency_key: str | None
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
            path = urllib.parse.urlsplit(req.full_url).path
            message = f"{req.get_method()} {path} failed: {reason}"
            if req.get_method() != "GET":
                message += (
                    "; the change may have been applied, check it before retrying"
                    " (a create with the same idempotency key)"
                )
            raise TelloApiConnectionError(message, idempotency_key) from exc


def _check_idempotency_key(key: str) -> None:
    if not 1 <= len(key.encode()) <= 255:
        raise ValueError("idempotency_key must be 1 to 255 bytes")
    if "," in key or any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in key):
        raise ValueError(
            "idempotency_key must not contain commas or control characters"
        )


def _check_id(value: str, name: str = "id") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return urllib.parse.quote(value, safe="")


def _result(
    status: int, raw: bytes, expect: tuple[int, ...], idempotency_key: str | None
) -> dict[str, Any]:
    if not 200 <= status <= 299:
        raise _api_error(status, raw, idempotency_key)
    if status not in expect:
        raise TelloApiError(
            status,
            "invalid_response",
            f"unexpected HTTP status {status}",
            None,
            idempotency_key,
        )
    if status == 204:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise TelloApiError(
            status,
            "invalid_response",
            "response is not a JSON object",
            None,
            idempotency_key,
        )
    return body


def _api_error(status: int, raw: bytes, idempotency_key: str | None) -> TelloApiError:
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
            idempotency_key,
        )
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = f"HTTP {status}"
    return TelloApiError(status, f"http_{status}", phrase, None, idempotency_key)


class _Collection:
    """get / create / update / delete of one collection (``/tools`` …).

    Creates, updates and deletes save, deploy and publish at once: the next
    call uses the result.
    """

    _path: str

    def __init__(self, transport: _Transport) -> None:
        self._t = transport

    async def get(self, id: str) -> dict[str, Any]:
        """``GET /{collection}/{id}`` → the item with its full settings."""
        return await self._t.request(
            "GET", f"{self._path}/{_check_id(id)}", expect=(200,)
        )

    async def create(
        self, body: dict[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """``POST /{collection}`` (``201``) → the created item.

        With ``idempotency_key``, resending the same body returns the first
        result instead of creating another item.
        """
        return await self._t.request(
            "POST",
            self._path,
            expect=(201,),
            body=body,
            idempotency_key=idempotency_key,
        )

    async def update(self, id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """``PATCH /{collection}/{id}``: change only the fields in ``patch``."""
        return await self._t.request(
            "PATCH", f"{self._path}/{_check_id(id)}", expect=(200,), body=patch
        )

    async def delete(self, id: str) -> None:
        """``DELETE /{collection}/{id}`` (``204``)."""
        await self._t.request("DELETE", f"{self._path}/{_check_id(id)}", expect=(204,))


class ToolsApi(_Collection):
    """``/tools``: tools agents can use during a call."""

    _path = "/tools"

    async def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> dict[str, Any]:
        """``GET /tools`` → one page ``{"data": [...], "nextCursor": str | None}``."""
        query: dict[str, Any] = {}
        if limit is not None:
            query["limit"] = limit
        if cursor is not None:
            query["cursor"] = cursor
        return await self._t.request("GET", "/tools", expect=(200,), query=query)


class AgentsApi(_Collection):
    """``/agents``: portal agents."""

    _path = "/agents"

    async def list(self) -> dict[str, Any]:
        """``GET /agents`` → ``{"data": [{"id", "name", "description", "isDefault"}]}``."""
        return await self._t.request("GET", "/agents", expect=(200,))


class CrewGenerationsApi:
    """``/crew-generations``: crew generation jobs started by ``crews.generate``."""

    def __init__(self, transport: _Transport) -> None:
        self._t = transport

    async def get(self, id: str) -> dict[str, Any]:
        """``GET /crew-generations/{id}`` → the job.

        ``status`` is ``"running"``, ``"succeeded"`` (with ``crew``) or
        ``"failed"`` (with ``error``, possibly with the crew it left behind).
        """
        return await self._t.request(
            "GET", f"/crew-generations/{_check_id(id)}", expect=(200,)
        )


class CrewsApi(_Collection):
    """``/crews``: crews of agents that hand a call over to each other."""

    _path = "/crews"

    def __init__(self, transport: _Transport, generations: CrewGenerationsApi) -> None:
        super().__init__(transport)
        self._generations = generations

    async def list(self) -> dict[str, Any]:
        """``GET /crews`` → ``{"data": [...]}``."""
        return await self._t.request("GET", "/crews", expect=(200,))

    async def generate(
        self, body: dict[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """``POST /crews/generate`` → the job ``{"id", "status": "running", …}``.

        Builds, deploys and publishes a crew from ``body["goal"]``. The account
        builds one crew at a time: the same goal while it runs (or shortly
        after it succeeded) returns that job (``200``) instead of a new one
        (``202``); another goal is ``crew_generation_in_progress`` with the
        running job in ``data.id``. Uses the long timeout.
        """
        return await self._t.request(
            "POST",
            "/crews/generate",
            expect=(200, 202),
            body=body,
            idempotency_key=idempotency_key,
            long=True,
        )

    async def generate_and_wait(
        self,
        body: dict[str, Any],
        *,
        poll_interval: float = 2.0,
        timeout: float = 600.0,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """:meth:`generate`, then poll the job until it is no longer running.

        Returns the finished job. A ``"failed"`` job is returned too, not
        raised: branch on ``job["status"]``. Raises :class:`TimeoutError`
        (with the job id) when the job still runs after ``timeout`` seconds;
        the job keeps running on the server.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        job = await self.generate(body, idempotency_key=idempotency_key)
        if job.get("status") != "running":
            return job
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise TelloApiError(
                200, "invalid_response", "crew generation job has no id"
            )
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"crew generation {job_id} still running after {timeout} seconds"
                )
            await asyncio.sleep(min(poll_interval, remaining))
            job = await self._generations.get(job_id)
            if job.get("status") != "running":
                return job


class CallDraftsApi:
    """``/call-drafts``: review the scenario of a call before placing it.

    :meth:`confirm` places a **real, billed** phone call. A draft is answered
    ``201`` whatever its ``status`` (``pendingConfirmation``,
    ``needsClarification``, ``refused`` or ``confirmed``): branch on it.
    All three requests use the long timeout.
    """

    def __init__(self, transport: _Transport) -> None:
        self._t = transport

    async def create(
        self, body: dict[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """``POST /call-drafts`` (``201``) → the draft.

        An agent with a ready scenario may be called at once (``status``
        ``confirmed`` with ``callId``); pass ``idempotency_key`` to resend safely.
        """
        return await self._t.request(
            "POST",
            "/call-drafts",
            expect=(201,),
            body=body,
            idempotency_key=idempotency_key,
            long=True,
        )

    async def revise(
        self, draft_id: str, request: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """``POST /call-drafts/{id}/revise`` (``200``) → a new draft with a **new id**.

        The revised draft can no longer be confirmed.
        """
        return await self._t.request(
            "POST",
            f"/call-drafts/{_check_id(draft_id, 'draft_id')}/revise",
            expect=(200,),
            body={"request": request},
            idempotency_key=idempotency_key,
            long=True,
        )

    async def confirm(
        self, draft_id: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """``POST /call-drafts/{id}/confirm`` (``201``) → the placed call.

        Places a real, billed call. The API requires an ``Idempotency-Key``:
        without ``idempotency_key`` a UUID v4 is generated. The key sent is on
        any :class:`TelloApiError` / :class:`TelloApiConnectionError` raised,
        so a retry can reuse it and replay the placed call instead of dialing
        again.
        """
        path = f"/call-drafts/{_check_id(draft_id, 'draft_id')}/confirm"
        return await self._t.request(
            "POST",
            path,
            expect=(201,),
            idempotency_key=idempotency_key
            if idempotency_key is not None
            else str(uuid.uuid4()),
            long=True,
        )


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
            raise ValueError(
                f"api_key is required (pass api_key=... or set ${ENV_API_KEY})"
            )
        self._transport = _Transport(
            key, _resolve_api_url(api_url), timeout, long_timeout
        )
        self.tools = ToolsApi(self._transport)
        self.agents = AgentsApi(self._transport)
        self.crew_generations = CrewGenerationsApi(self._transport)
        self.crews = CrewsApi(self._transport, self.crew_generations)
        self.call_drafts = CallDraftsApi(self._transport)

    @property
    def api_url(self) -> str:
        """The base URL requests go to, without a trailing slash."""
        return self._transport.api_url

    def __repr__(self) -> str:
        return f"TelloApi(api_url={self.api_url!r})"
