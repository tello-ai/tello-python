"""Client configuration."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_URL = "wss://api.telloai.io/sdk"

#: Environment variables read when ``api_key`` / ``url`` are not passed explicitly.
ENV_API_KEY = "TELLO_API_KEY"
ENV_URL = "TELLO_URL"

#: Default base URL of the public REST API used by :class:`tello.api.TelloApi`.
DEFAULT_API_URL = "https://api.telloai.io/v1"

#: Environment variable read when ``api_url`` is not passed to ``TelloApi``.
ENV_API_URL = "TELLO_API_URL"


@dataclass
class ClientConfig:
    """Connection settings for :class:`tello.client.TelloClient`.

    ``api_key`` is sent in the first application frame after the socket opens
    (the ``auth`` frame's ``token`` field) — never on the WS upgrade request or
    in the URL query. ``url`` is the gateway ``/sdk`` endpoint. ``open_timeout`` bounds
    both the WS handshake and the wait for the server's ``auth.ok`` reply.
    """

    api_key: str
    url: str = DEFAULT_URL
    open_timeout: float = 10.0
    close_timeout: float = 5.0
