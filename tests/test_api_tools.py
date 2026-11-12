"""TelloApi.tools against a local fake API: CRUD, idempotency keys, statuses."""

from __future__ import annotations

import socket

import pytest

from tello import TelloApi, TelloApiConnectionError, TelloApiError

KEY = "tello_live_secret"
TOOL = {"id": "t_1", "type": "endCall", "name": "끝내기", "revision": 1, "extra": {"x": 1}}


@pytest.fixture
def api(fake_api) -> TelloApi:
    return TelloApi(api_key=KEY, api_url=fake_api.url)


async def test_list_without_paging_sends_no_query(api, fake_api):
    page = {"data": [TOOL], "nextCursor": None}
    fake_api.reply(200, page)

    assert await api.tools.list() == page
    assert (fake_api.last.method, fake_api.last.path) == ("GET", "/v1/tools")


async def test_list_sends_limit_and_cursor(api, fake_api):
    fake_api.reply(200, {"data": [], "nextCursor": "c2"})

    await api.tools.list(limit=1, cursor="c 1/+")

    assert fake_api.last.path == "/v1/tools?limit=1&cursor=c+1%2F%2B"


async def test_get_encodes_the_id_in_the_path(api, fake_api):
    fake_api.reply(200, TOOL)

    assert await api.tools.get("t/1 ?") == TOOL
    assert (fake_api.last.method, fake_api.last.path) == ("GET", "/v1/tools/t%2F1%20%3F")


async def test_empty_id_is_rejected_without_a_request(api, fake_api):
    with pytest.raises(ValueError, match="id"):
        await api.tools.get("")
    with pytest.raises(ValueError, match="id"):
        await api.tools.update("", {"name": "x"})
    with pytest.raises(ValueError, match="id"):
        await api.tools.delete("")
    assert fake_api.requests == []


async def test_create_posts_json_and_returns_the_tool(api, fake_api):
    fake_api.reply(201, TOOL)
    body = {"type": "endCall", "name": "끝내기", "functionName": "end_call"}

    assert await api.tools.create(body) == TOOL
    req = fake_api.last
    assert (req.method, req.path) == ("POST", "/v1/tools")
    assert req.headers["content-type"] == "application/json"
    assert req.json() == body
    assert "idempotency-key" not in req.headers


async def test_create_sends_the_given_idempotency_key(api, fake_api):
    fake_api.reply(201, TOOL)

    await api.tools.create({"type": "endCall"}, idempotency_key="tool-001")

    assert fake_api.last.headers["idempotency-key"] == "tool-001"


async def test_create_error_carries_the_idempotency_key(api, fake_api):
    fake_api.error(409, "idempotency_key_reused", "Idempotency key reused")

    with pytest.raises(TelloApiError) as info:
        await api.tools.create({"type": "endCall"}, idempotency_key="tool-001")

    assert info.value.code == "idempotency_key_reused"
    assert info.value.idempotency_key == "tool-001"


async def test_create_answered_200_is_invalid_response(api, fake_api):
    fake_api.reply(200, TOOL)

    with pytest.raises(TelloApiError) as info:
        await api.tools.create({"type": "endCall"}, idempotency_key="k")

    assert (info.value.status, info.value.code) == (200, "invalid_response")
    assert info.value.idempotency_key == "k"


@pytest.mark.parametrize("key", ["", "a,b", "a\nb", "a\x7fb", "x" * 256, "가" * 86])
async def test_invalid_idempotency_key_is_rejected_without_a_request(api, fake_api, key):
    with pytest.raises(ValueError, match="idempotency_key"):
        await api.tools.create({"type": "endCall"}, idempotency_key=key)
    assert fake_api.requests == []


async def test_idempotency_key_of_255_bytes_is_accepted(api, fake_api):
    fake_api.reply(201, TOOL)

    await api.tools.create({"type": "endCall"}, idempotency_key="k" * 255)

    assert fake_api.last.headers["idempotency-key"] == "k" * 255


async def test_write_connection_error_carries_the_idempotency_key():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    api = TelloApi(api_key=KEY, api_url=f"http://127.0.0.1:{port}/v1")

    with pytest.raises(TelloApiConnectionError) as info:
        await api.tools.create({"type": "endCall"}, idempotency_key="tool-001")

    assert info.value.idempotency_key == "tool-001"
    assert "may have been applied" in str(info.value)


async def test_update_patches_only_the_given_fields(api, fake_api):
    fake_api.reply(200, {**TOOL, "description": "d"})

    result = await api.tools.update("t_1", {"description": "d"})

    assert result["description"] == "d"
    req = fake_api.last
    assert (req.method, req.path) == ("PATCH", "/v1/tools/t_1")
    assert req.headers["content-type"] == "application/json"
    assert req.json() == {"description": "d"}
    assert "idempotency-key" not in req.headers


async def test_delete_returns_none_on_204(api, fake_api):
    fake_api.reply(204)

    assert await api.tools.delete("t_1") is None
    assert (fake_api.last.method, fake_api.last.path) == ("DELETE", "/v1/tools/t_1")


async def test_delete_answered_200_is_invalid_response(api, fake_api):
    fake_api.reply(200, {})

    with pytest.raises(TelloApiError) as info:
        await api.tools.delete("t_1")

    assert info.value.code == "invalid_response"


async def test_not_found_keeps_the_snake_case_code_and_data(api, fake_api):
    fake_api.error(404, "tool_not_found", "Tool not found", {"reason": "missing"})

    with pytest.raises(TelloApiError) as info:
        await api.tools.get("t_404")

    assert (info.value.status, info.value.code) == (404, "tool_not_found")
    assert info.value.data == {"reason": "missing"}
