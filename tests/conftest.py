"""Shared fixtures: a local fake of the Tello public REST API.

The fake records every request (method, path with query, lower-cased headers,
raw body) and answers from a queue of scripted replies. It never reaches the
real API.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class Reply:
    status: int
    body: bytes = b""
    content_type: str | None = "application/json"
    delay: float = 0.0


@dataclass
class FakeApi:
    port: int = 0
    requests: list[Recorded] = field(default_factory=list)
    replies: list[Reply] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def reply(
        self,
        status: int,
        body: Any = None,
        *,
        raw: bytes | None = None,
        content_type: str | None = "application/json",
        delay: float = 0.0,
    ) -> None:
        """Queue one reply. ``body`` is sent as JSON, ``raw`` as is."""
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        self.replies.append(Reply(status, data, content_type, delay))

    def error(self, status: int, code: str, message: str, data: Any = None) -> None:
        self.reply(
            status, {"statusCode": status, "message": message, "error": code, "data": data}
        )

    @property
    def last(self) -> Recorded:
        return self.requests[-1]


def _handler(fake: FakeApi) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            fake.requests.append(
                Recorded(
                    self.command,
                    self.path,
                    {k.lower(): v for k, v in self.headers.items()},
                    body,
                )
            )
            reply = fake.replies.pop(0) if fake.replies else Reply(500, b"no reply queued")
            if reply.delay:
                time.sleep(reply.delay)
            self.send_response(reply.status)
            if reply.content_type and reply.body:
                self.send_header("Content-Type", reply.content_type)
            if reply.status != 204:
                self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            if reply.status != 204:
                self.wfile.write(reply.body)

        do_GET = do_POST = do_PATCH = do_DELETE = _serve

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeApi]:
    monkeypatch.delenv("TELLO_API_KEY", raising=False)
    monkeypatch.delenv("TELLO_API_URL", raising=False)
    fake = FakeApi()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    server.daemon_threads = True
    fake.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
