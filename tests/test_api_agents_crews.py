"""TelloApi.agents and TelloApi.crews CRUD against a local fake API."""

from __future__ import annotations

import pytest

from tello import TelloApi, TelloApiError

KEY = "tello_live_secret"


@pytest.fixture
def api(fake_api) -> TelloApi:
    return TelloApi(api_key=KEY, api_url=fake_api.url)


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_list(api, fake_api, name):
    page = {"data": [{"id": "x1", "name": "n", "description": None}]}
    fake_api.reply(200, page)

    assert await getattr(api, name).list() == page
    assert (fake_api.last.method, fake_api.last.path) == ("GET", f"/v1/{name}")


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_get(api, fake_api, name):
    fake_api.reply(200, {"id": "x 1", "name": "n"})

    assert await getattr(api, name).get("x 1") == {"id": "x 1", "name": "n"}
    assert (fake_api.last.method, fake_api.last.path) == ("GET", f"/v1/{name}/x%201")


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_create_with_idempotency_key(api, fake_api, name):
    fake_api.reply(201, {"id": "x1", "revision": 1})

    result = await getattr(api, name).create({"name": "n"}, idempotency_key="k-1")

    assert result == {"id": "x1", "revision": 1}
    req = fake_api.last
    assert (req.method, req.path) == ("POST", f"/v1/{name}")
    assert req.json() == {"name": "n"}
    assert req.headers["content-type"] == "application/json"
    assert req.headers["idempotency-key"] == "k-1"


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_create_without_idempotency_key(api, fake_api, name):
    fake_api.reply(201, {"id": "x1"})

    await getattr(api, name).create({"name": "n"})

    assert "idempotency-key" not in fake_api.last.headers


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_update(api, fake_api, name):
    fake_api.reply(200, {"id": "x1", "name": "m"})

    assert await getattr(api, name).update("x1", {"name": "m"}) == {
        "id": "x1",
        "name": "m",
    }
    req = fake_api.last
    assert (req.method, req.path, req.json()) == (
        "PATCH",
        f"/v1/{name}/x1",
        {"name": "m"},
    )


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_update_answered_201_is_invalid_response(api, fake_api, name):
    fake_api.reply(201, {"id": "x1"})

    with pytest.raises(TelloApiError) as info:
        await getattr(api, name).update("x1", {"name": "m"})

    assert info.value.code == "invalid_response"


@pytest.mark.parametrize("name", ["agents", "crews"])
async def test_delete(api, fake_api, name):
    fake_api.reply(204)

    assert await getattr(api, name).delete("x1") is None
    assert (fake_api.last.method, fake_api.last.path) == ("DELETE", f"/v1/{name}/x1")


async def test_agent_in_use_error(api, fake_api):
    fake_api.error(
        409, "agent_in_use", "Agent is in use", {"reason": "crew", "detail": "크루"}
    )

    with pytest.raises(TelloApiError) as info:
        await api.agents.delete("a1")

    assert (info.value.status, info.value.code) == (409, "agent_in_use")
    assert info.value.data == {"reason": "crew", "detail": "크루"}
