"""TelloApi construction, transport and error mapping against a local fake API.

Exercised through ``agents.list()``, the simplest request. Per-resource
behavior is in the ``test_api_*`` files.
"""

from __future__ import annotations

import socket

import pytest

from tello import (
    TelloApi,
    TelloApiConnectionError,
    TelloApiError,
    TelloError,
    __version__,
)

KEY = "tello_live_secret"


def api(fake_api, **kwargs) -> TelloApi:
    return TelloApi(api_key=KEY, api_url=fake_api.url, **kwargs)


# --- construction -----------------------------------------------------------


async def test_api_key_falls_back_to_env(fake_api, monkeypatch):
    monkeypatch.setenv("TELLO_API_KEY", "from-env")
    client = TelloApi(api_url=fake_api.url)
    fake_api.reply(200, {"data": []})

    await client.agents.list()
    assert fake_api.last.headers["authorization"] == "Bearer from-env"


def test_missing_api_key_is_rejected_like_the_ws_client(fake_api):
    with pytest.raises(ValueError, match=r"api_key is required .*TELLO_API_KEY"):
        TelloApi(api_url=fake_api.url)


def test_empty_api_key_is_rejected(fake_api):
    with pytest.raises(ValueError, match="api_key is required"):
        TelloApi(api_key="", api_url=fake_api.url)


def test_default_api_url_is_production(monkeypatch):
    monkeypatch.delenv("TELLO_API_URL", raising=False)
    assert TelloApi(api_key=KEY).api_url == "https://api.telloai.io/v1"


def test_api_url_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("TELLO_API_URL", "https://dev.example.com/v1")
    assert TelloApi(api_key=KEY).api_url == "https://dev.example.com/v1"


def test_argument_api_url_wins_over_env(monkeypatch):
    monkeypatch.setenv("TELLO_API_URL", "https://dev.example.com/v1")
    client = TelloApi(api_key=KEY, api_url="https://other.example.com/v1")
    assert client.api_url == "https://other.example.com/v1"


def test_trailing_slashes_are_removed():
    assert TelloApi(api_key=KEY, api_url="https://x.example.com/v1/").api_url == (
        "https://x.example.com/v1"
    )


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8080/v1", "http://localhost/v1", "http://[::1]:9/v1"]
)
def test_http_is_allowed_on_loopback(url):
    assert TelloApi(api_key=KEY, api_url=url).api_url == url


@pytest.mark.parametrize(
    "url",
    ["http://api.telloai.io/v1", "http://10.0.0.1/v1", "ftp://x/v1", "api.telloai.io/v1"],
)
def test_other_urls_are_rejected(url):
    with pytest.raises(ValueError, match="api_url"):
        TelloApi(api_key=KEY, api_url=url)


def test_repr_never_shows_the_key(fake_api):
    client = api(fake_api)
    assert KEY not in repr(client)
    assert fake_api.url in repr(client)


# --- request shape ----------------------------------------------------------


async def test_get_sends_auth_accept_and_user_agent(fake_api):
    fake_api.reply(200, {"data": [{"id": "a1", "name": "n", "isDefault": True}]})

    result = await api(fake_api).agents.list()

    assert result == {"data": [{"id": "a1", "name": "n", "isDefault": True}]}
    req = fake_api.last
    assert (req.method, req.path) == ("GET", "/v1/agents")
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["accept"] == "application/json"
    assert req.headers["user-agent"] == f"tello-python-sdk/{__version__}"
    assert "content-type" not in req.headers
    assert "idempotency-key" not in req.headers
    assert req.body == b""


# --- errors -----------------------------------------------------------------


async def test_error_envelope_becomes_tello_api_error(fake_api):
    fake_api.error(403, "insufficient_scope", "Missing scope", {"requiredScope": "agents:read"})

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    err = info.value
    assert isinstance(err, TelloError)
    assert err.status == 403
    assert err.code == "insufficient_scope"
    assert err.message == "Missing scope"
    assert str(err) == "Missing scope"
    assert err.data == {"requiredScope": "agents:read"}
    assert err.idempotency_key is None


async def test_error_envelope_with_null_data(fake_api):
    fake_api.error(401, "unauthenticated", "Invalid API key")

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    assert info.value.code == "unauthenticated"
    assert info.value.data is None


async def test_non_json_error_uses_http_status(fake_api):
    fake_api.reply(502, raw=b"<html>bad gateway</html>", content_type="text/html")

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    err = info.value
    assert (err.status, err.code, err.message, err.data) == (502, "http_502", "Bad Gateway", None)


async def test_json_error_without_envelope_uses_http_status(fake_api):
    fake_api.reply(500, {"oops": True})

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    assert (info.value.code, info.value.message) == ("http_500", "Internal Server Error")


async def test_redirect_is_not_followed(fake_api):
    fake_api.reply(302, raw=b"", content_type=None)

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    assert info.value.code == "http_302"
    assert len(fake_api.requests) == 1


async def test_unexpected_success_status_is_invalid_response(fake_api):
    fake_api.reply(201, {"data": []})

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    assert (info.value.status, info.value.code) == (201, "invalid_response")


async def test_success_body_that_is_not_an_object_is_invalid_response(fake_api):
    fake_api.reply(200, [1, 2])

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    assert info.value.code == "invalid_response"


async def test_success_body_that_is_not_json_is_invalid_response(fake_api):
    fake_api.reply(200, raw=b"not json", content_type="text/plain")

    with pytest.raises(TelloApiError) as info:
        await api(fake_api).agents.list()

    assert info.value.code == "invalid_response"


async def test_refused_connection_is_a_connection_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    client = TelloApi(api_key=KEY, api_url=f"http://127.0.0.1:{port}/v1")

    with pytest.raises(TelloApiConnectionError) as info:
        await client.agents.list()

    err = info.value
    assert isinstance(err, TelloError)
    assert not isinstance(err, TelloApiError)
    assert err.__cause__ is not None
    assert err.idempotency_key is None
    assert KEY not in str(err)


async def test_timeout_is_a_connection_error(fake_api):
    fake_api.reply(200, {"data": []}, delay=1.0)

    with pytest.raises(TelloApiConnectionError) as info:
        await api(fake_api, timeout=0.2).agents.list()

    assert info.value.__cause__ is not None
