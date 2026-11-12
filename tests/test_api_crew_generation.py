"""crews.generate, crew_generations.get and crews.generate_and_wait against a local fake API."""

from __future__ import annotations

import pytest

from tello import TelloApi, TelloApiConnectionError, TelloApiError

KEY = "tello_live_secret"
GOAL = {"goal": "치과 예약 고객에게 전화해 내일 예약을 확인한다"}
RUNNING = {"id": "cg_1", "status": "running", "goal": GOAL["goal"]}
SUCCEEDED = {"id": "cg_1", "status": "succeeded", "crew": {"id": "cr_1"}}
FAILED = {"id": "cg_1", "status": "failed", "error": {"code": "x", "message": "m"}}


@pytest.fixture
def api(fake_api) -> TelloApi:
    return TelloApi(api_key=KEY, api_url=fake_api.url)


async def test_generate_posts_the_goal_and_returns_the_job(api, fake_api):
    fake_api.reply(202, RUNNING)

    assert await api.crews.generate(GOAL) == RUNNING
    req = fake_api.last
    assert (req.method, req.path, req.json()) == ("POST", "/v1/crews/generate", GOAL)
    assert req.headers["content-type"] == "application/json"
    assert "idempotency-key" not in req.headers


async def test_generate_accepts_200_for_the_job_of_the_same_goal(api, fake_api):
    fake_api.reply(200, SUCCEEDED)

    assert await api.crews.generate(GOAL) == SUCCEEDED


async def test_generate_answered_201_is_invalid_response(api, fake_api):
    fake_api.reply(201, RUNNING)

    with pytest.raises(TelloApiError) as info:
        await api.crews.generate(GOAL)

    assert info.value.code == "invalid_response"


async def test_generate_sends_the_given_idempotency_key(api, fake_api):
    fake_api.reply(202, RUNNING)

    await api.crews.generate(GOAL, idempotency_key="gen-1")

    assert fake_api.last.headers["idempotency-key"] == "gen-1"


async def test_generate_uses_the_long_timeout(fake_api):
    api = TelloApi(api_key=KEY, api_url=fake_api.url, timeout=0.1, long_timeout=5)
    fake_api.reply(202, RUNNING, delay=0.3)

    assert await api.crews.generate(GOAL) == RUNNING


async def test_generation_lookup_uses_the_short_timeout(fake_api):
    api = TelloApi(api_key=KEY, api_url=fake_api.url, timeout=0.1, long_timeout=5)
    fake_api.reply(200, RUNNING, delay=0.3)

    with pytest.raises(TelloApiConnectionError):
        await api.crew_generations.get("cg_1")


async def test_get_generation(api, fake_api):
    fake_api.reply(200, SUCCEEDED)

    assert await api.crew_generations.get("cg_1") == SUCCEEDED
    assert (fake_api.last.method, fake_api.last.path) == ("GET", "/v1/crew-generations/cg_1")


async def test_get_unknown_generation(api, fake_api):
    fake_api.error(404, "crew_generation_not_found", "Crew generation not found")

    with pytest.raises(TelloApiError) as info:
        await api.crew_generations.get("999999")

    assert info.value.code == "crew_generation_not_found"


async def test_get_generation_rejects_an_empty_id(api, fake_api):
    with pytest.raises(ValueError, match="id"):
        await api.crew_generations.get("")
    assert fake_api.requests == []


async def test_generate_and_wait_polls_until_the_job_ends(api, fake_api):
    fake_api.reply(202, RUNNING)
    fake_api.reply(200, RUNNING)
    fake_api.reply(200, SUCCEEDED)

    job = await api.crews.generate_and_wait(GOAL, poll_interval=0.01, idempotency_key="g")

    assert job == SUCCEEDED
    assert [r.path for r in fake_api.requests] == [
        "/v1/crews/generate",
        "/v1/crew-generations/cg_1",
        "/v1/crew-generations/cg_1",
    ]
    assert fake_api.requests[0].headers["idempotency-key"] == "g"


async def test_generate_and_wait_returns_a_failed_job(api, fake_api):
    fake_api.reply(202, RUNNING)
    fake_api.reply(200, FAILED)

    assert await api.crews.generate_and_wait(GOAL, poll_interval=0.01) == FAILED


async def test_generate_and_wait_returns_a_finished_job_without_polling(api, fake_api):
    fake_api.reply(200, SUCCEEDED)

    assert await api.crews.generate_and_wait(GOAL, poll_interval=0.01) == SUCCEEDED
    assert len(fake_api.requests) == 1


async def test_generate_and_wait_times_out_with_the_job_id(api, fake_api):
    fake_api.reply(202, RUNNING)
    for _ in range(50):
        fake_api.reply(200, RUNNING)

    with pytest.raises(TimeoutError, match="cg_1"):
        await api.crews.generate_and_wait(GOAL, poll_interval=0.02, timeout=0.1)


async def test_generate_and_wait_raises_generation_in_progress(api, fake_api):
    fake_api.error(409, "crew_generation_in_progress", "In progress", {"id": "cg_0"})

    with pytest.raises(TelloApiError) as info:
        await api.crews.generate_and_wait(GOAL, poll_interval=0.01)

    assert info.value.code == "crew_generation_in_progress"
    assert info.value.data == {"id": "cg_0"}


async def test_generate_and_wait_rejects_a_running_job_without_id(api, fake_api):
    fake_api.reply(202, {"status": "running"})

    with pytest.raises(TelloApiError) as info:
        await api.crews.generate_and_wait(GOAL, poll_interval=0.01)

    assert info.value.code == "invalid_response"
