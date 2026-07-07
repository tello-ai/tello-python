"""Client configuration."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_URL = "ws://localhost:3000/sdk"

#: Environment variables read when ``api_key`` / ``url`` are not passed explicitly.
ENV_API_KEY = "TELLO_API_KEY"
ENV_URL = "TELLO_URL"


@dataclass
class ClientConfig:
    """Connection settings for :class:`tello.client.TelloClient`.

    ``api_key`` is sent as ``Authorization: Bearer <api_key>`` on the WS
    upgrade request. ``url`` is the gateway ``/sdk`` endpoint.
    """

    api_key: str
    url: str = DEFAULT_URL
    open_timeout: float = 10.0
    close_timeout: float = 5.0
