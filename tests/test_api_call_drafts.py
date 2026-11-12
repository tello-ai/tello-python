"""TelloApi.call_drafts against a local fake API. No real call is ever placed."""

from __future__ import annotations

import socket
import uuid

import pytest

from tello import TelloApi, TelloApiConnectionError, TelloApiError

KEY = "tello_live_secret"
BODY = {"agentId": "a_1", "to": "+821012345678", "instructions": "내일 예약 확인"}
CALL = {"id": "c_1", "status": "dialing"}


@pytest.fixture
def api(fake_api) -> TelloApi:
    return TelloApi(api_key=KEY, api_url=fake_api.url)


def _uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


@pytest.mark.parametrize(
    "status", ["pendingConfirmation", "needsClarification", "refused", "confirmed"]
)
async def test_create_returns_every_draft_status(api, fake_api, status):
    draft = {"id": "cd_1", "status": status}
    fake_api.reply(201, draft)

    assert await api.call_drafts.create(BODY) == draft
    req = fake_api.last
    assert (req.method, req.path, req.json()) == ("POST", "/v1/call-drafts", BODY)
    assert req.headers["content-type"] == "application/json"
    assert "idempotency-key" not in req.headers


async def test_create_sends_the_given_idempotency_key(api, fake_api):
    fake_api.reply(201, {"id": "cd_1", "status": "pendingConfirmation"})

    await api.call_drafts.create(BODY, idempotency_key="draft-1")

    assert fake_api.last.headers["idempotency-key"] == "draft-1"


async def test_create_answered_200_is_invalid_response(api, fake_api):
    fake_api.reply(200, {"id": "cd_1"})

    with pytest.raises(TelloApiError) as info:
        await api.call_drafts.create(BODY)

    assert info.value.code == "invalid_response"


async def test_create_uses_the_long_timeout(fake_api):
    api = TelloApi(api_key=KEY, api_url=fake_api.url, timeout=0.1, long_timeout=5)
    fake_api.reply(201, {"id": "cd_1"}, delay=0.3)

    assert await api.call_drafts.create(BODY) == {"id": "cd_1"}


async def test_revise_posts_the_request_and_returns_the_new_draft(api, fake_api):
    fake_api.reply(200, {"id": "cd_2", "status": "pendingConfirmation"})

    draft = await api.call_drafts.revise("cd_1", "오후로 바꿔줘", idempotency_key="r-1")

    assert draft["id"] == "cd_2"
    req = fake_api.last
    assert (req.method, req.path) == ("POST", "/v1/call-drafts/cd_1/revise")
    assert req.json() == {"request": "오후로 바꿔줘"}
    assert req.headers["idempotency-key"] == "r-1"


async def test_revise_without_key_sends_none(api, fake_api):
    fake_api.reply(200, {"id": "cd_2"})

    await api.call_drafts.revise("cd_1", "x")

    assert "idempotency-key" not in fake_api.last.headers


async def test_revise_answered_201_is_invalid_response(api, fake_api):
    fake_api.reply(201, {"id": "cd_2"})

    with pytest.raises(TelloApiError) as info:
        await api.call_drafts.revise("cd_1", "x")

    assert info.value.code == "invalid_response"


async def test_revise_uses_the_long_timeout(fake_api):
    api = TelloApi(api_key=KEY, api_url=fake_api.url, timeout=0.1, long_timeout=5)
    fake_api.reply(200, {"id": "cd_2"}, delay=0.3)

    assert await api.call_drafts.revise("cd_1", "x") == {"id": "cd_2"}


async def test_confirm_posts_no_body_and_returns_the_call(api, fake_api):
    fake_api.reply(201, CALL)

    assert await api.call_drafts.confirm("cd_1", idempotency_key="confirm-1") == CALL
    req = fake_api.last
    assert (req.method, req.path) == ("POST", "/v1/call-drafts/cd_1/confirm")
    assert req.body == b""
    assert "content-type" not in req.headers
    assert req.headers["idempotency-key"] == "confirm-1"


async def test_confirm_generates_a_uuid4_key_when_none_is_given(api, fake_api):
    fake_api.reply(201, CALL)

    await api.call_drafts.confirm("cd_1")

    assert _uuid4(fake_api.last.headers["idempotency-key"])


async def test_confirm_error_carries_the_generated_key(api, fake_api):
    fake_api.error(404, "draft_not_found", "Draft not found")

    with pytest.raises(TelloApiError) as info:
        await api.call_drafts.confirm("cd_999999")

    assert info.value.code == "draft_not_found"
    assert info.value.idempotency_key == fake_api.last.headers["idempotency-key"]
    assert _uuid4(info.value.idempotency_key)


async def test_confirm_connection_error_carries_the_generated_key():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    api = TelloApi(api_key=KEY, api_url=f"http://127.0.0.1:{port}/v1")

    with pytest.raises(TelloApiConnectionError) as info:
        await api.call_drafts.confirm("cd_1")

    assert _uuid4(info.value.idempotency_key)


async def test_confirm_answered_200_is_invalid_response(api, fake_api):
    fake_api.reply(200, CALL)

    with pytest.raises(TelloApiError) as info:
        await api.call_drafts.confirm("cd_1", idempotency_key="k")

    assert (info.value.code, info.value.idempotency_key) == ("invalid_response", "k")


async def test_confirm_uses_the_long_timeout(fake_api):
    api = TelloApi(api_key=KEY, api_url=fake_api.url, timeout=0.1, long_timeout=5)
    fake_api.reply(201, CALL, delay=0.3)

    assert await api.call_drafts.confirm("cd_1") == CALL


async def test_confirm_rejects_an_invalid_key_without_a_request(api, fake_api):
    with pytest.raises(ValueError, match="idempotency_key"):
        await api.call_drafts.confirm("cd_1", idempotency_key="a,b")
    assert fake_api.requests == []


async def test_empty_draft_id_is_rejected_without_a_request(api, fake_api):
    with pytest.raises(ValueError, match="draft_id"):
        await api.call_drafts.revise("", "x")
    with pytest.raises(ValueError, match="draft_id"):
        await api.call_drafts.confirm("")
    assert fake_api.requests == []
