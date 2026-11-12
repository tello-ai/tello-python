[English](README.md) | **한국어**

# tello-ai-sdk (Python)

> 저장소: `tello-python` · PyPI 배포명: `tello-ai-sdk` · import: `tello`

Python용 Tello SDK. API 게이트웨이(api-gateway) `/sdk` 엔드포인트에 붙는 얇은
**WebSocket** 실시간 클라이언트와, 공개 REST 자원 API 클라이언트 `TelloApi`를
제공합니다. WebSocket 클라이언트는 대화의 두뇌를 맡습니다.
게이트웨이는 진행 중인 통화에서 상대방이 말한 턴을 실시간으로 넘겨주고,
핸들러가 만든 답변은 다시 통화로 전달됩니다.

> 실시간 프로토콜 계약은 [`docs/protocol/sdk-ws.v1.md`](docs/protocol/sdk-ws.v1.md)에
> 있습니다. REST 자원 API(도구·에이전트·크루·통화 초안)는 §6을 보세요.

## 1. 설치

```bash
pip install tello-ai-sdk     # Python 3.10 이상 필요. import 이름은 `tello`
```

## 2. API 키

키 인증은 애플리케이션 레벨 핸드셰이크로 이뤄집니다. 소켓이 열리자마자 SDK가
`token` 필드에 키를 담은 `auth` 프레임을 보내고, 서버의 `auth.ok`를 받은 뒤에야
나머지 동작이 시작됩니다. 키는 WS 업그레이드 요청이나 URL query에 실리지
않습니다. 전부 내부 처리라 auth를 직접 호출할 일은 없고, 인증이 끝나기 전에는
`connect()`(그리고 `async with`)가 성공하지 않습니다. 키는 포털에서 발급하세요
(Agent settings → Advanced → Agent-linked / SDK).

키는 인자로 직접 넘기거나 환경 변수로 지정합니다:

```bash
export TELLO_API_KEY="tello_live_xxx"
export TELLO_URL="wss://api.telloai.io/sdk"   # 선택. 기본값 wss://api.telloai.io/sdk
```

인자 없이 `TelloClient()`를 호출하면 `TELLO_API_KEY` / `TELLO_URL`을 읽습니다.
클라이언트는 URL 쿼리에 `sdk=python&version=<패키지 버전>&protocol=<PROTOCOL_VERSION>`을 붙입니다(기존 경로·쿼리는 유지). 서버는 이 값을 로그에만 남깁니다.

## 3. 연결 + 통화 시작

```python
import asyncio
from tello import TelloClient, EventType

async def main():
    async with TelloClient(api_key="tello_live_xxx", url="wss://api.telloai.io/sdk") as client:
        @client.on(EventType.USER_TURN)
        async def on_user_turn(event):
            await client.answer(text="확인했습니다. 계속 말씀해주세요.")

        await client.create_call(to="+821012345678", prompt="예약 확인")
        await client.wait_closed()

asyncio.run(main())
```

`TelloClient(...)`가 생성자입니다(Python에는 `new`가 없습니다). `async with`는
`connect()` / `aclose()`를 묶어 준 것뿐이니, 원하면 직접 호출해도 됩니다:

```python
client = TelloClient(api_key="tello_live_xxx", url="wss://api.telloai.io/sdk")
await client.connect()
client.on(EventType.USER_TURN, on_user_turn)
await client.create_call(to="+821012345678", prompt="예약 확인")
await client.wait_closed()
await client.aclose()
```

## 4. 실시간 턴 이벤트 (pub/sub)

`client.on(...)`으로 이벤트 타입별 핸들러를 구독합니다. 동기·비동기 모두
됩니다:

| `EventType` | 값 | 페이로드 필드 |
| --- | --- | --- |
| `CALL_CREATED` | `call.created` | `call_id`, `session_id` |
| `USER_TURN` | `user.turn` | `turn_index`, `text` |
| `AGENT_TURN` | `agent.turn` | `turn_index`, `text` |
| `ANSWER_ACCEPTED` | `answer.accepted` | `request_id?`, `message_id` |
| `DTMF_ACCEPTED` | `dtmf.accepted` | `request_id?`, `message_id`, `digits` |
| `CALL_SUMMARY` | `call.summary` | `request_id?`, `status`, `duration_seconds?`, `transcript?`, `summary?`, `credit_charged?` |
| `CALL_STATUS_CHANGED` | `call.statusChanged` | `status`, `previous_status` |
| `CALL_COMPLETED` | `call.completed` | `status` |
| `CALL_NO_ANSWER` | `call.noAnswer` | `status`, `failure_reason?` |
| `CALL_FAILED` | `call.failed` | `status`, `failure_reason?` |
| `ERROR` | `error` | `code`, `message`, `request_id?`, `question?` |
| `DISCONNECTED` | `disconnected` | SDK 자체 이벤트. WS가 닫힐 때 발생 |

위 페이로드 필드는 Python 속성 이름입니다. 실제 와이어 프레임은 camelCase 키를
씁니다(`sessionId`, `callId`, `turnIndex`, `previousStatus`, `failureReason`,
`requestId`). 모르는 `type`은 기본 `Event`로 떨어지므로, 앞으로 추가되는
이벤트도 구독자에게 그대로 전달됩니다.

명령: `await client.create_call(to, prompt="", metadata=None, request_id=None)`,
`await client.answer(text, message_id=None, request_id=None)`,
`await client.send_dtmf(digits, message_id=None, request_id=None)`, `await client.cancel()`,
`await client.get_summary(call_id, request_id=None)`. `create_call`은 항상
`requestId`를 보냅니다. 직접 넘긴 값을 쓰고, 생략하면 UUID를 생성해 씁니다.
명령마다 `request_id`를 따로 주거나 생략하세요(§5 참고).

`await client.wait_closed()`는 통화가 종료 상태(`call.completed` /
`call.noAnswer` / `call.failed`, 또는 status가 `cancelled`인
`call.statusChanged`)에 이르거나 연결이 닫히면 resolve 됩니다. `cancel()`을
보내면 게이트웨이는 그 cancelled `call.statusChanged`로 통화를 끝냅니다
(`previous_status`는 취소 직전 상태). 뒤따르는 `call.completed`는 없습니다.
진행 중인 대기는 핸들러가 이미 다음 통화를 시작했더라도 자기 통화가 끝나면
반환됩니다. 다음 통화를 기다리려면 `wait_closed()`를 다시 호출하세요. 통화의
`create_call`이 실패하면 대신 오류를 raise 합니다(§5 참고). 다른 명령의
오류로는 대기가 끝나지 않습니다.

## 5. 오류 처리

게이트웨이 오류 프레임은 예외와 1:1로 대응됩니다
([`docs/errors/errors.v1.json`](docs/errors/errors.v1.json) 참고):

| 게이트웨이 `code` | 예외 |
| --- | --- |
| `unauthenticated` | `AuthenticationError` (인증 핸드셰이크. 4401 종료 포함) |
| `ipNotAllowed` | `AuthenticationError` (인증 핸드셰이크. 서버용 키의 허용 IP 밖. 4401 종료. `.ip`에 판정한 주소) |
| `insufficientScope` | `PermissionDeniedError` (서버용 키에 그 명령의 권한이 없음. 연결은 유지. `.required_scope`에 필요한 권한) |
| `toRequired` | `ValidationError` |
| `callIdRequired` | `ValidationError` |
| `callNotFound` | `ValidationError` |
| `callNotCompleted` | `ValidationError` |
| `dtmfDigitsRequired` | `ValidationError` |
| `dtmfDigitsInvalid` | `ValidationError` |
| `callAlreadyActive` | `CallAlreadyActiveError` |
| `noActiveCall` | `NoActiveCallError` |
| `callRejected` | `CallRejectedError` (`.question` 포함) |
| `internalError` | `TelloServerError` |

모든 오류는 게이트웨이 코드를 `.code`에 담고 있습니다. **분기는 `.code`로 하고
`.args[0]`로는 하지 마세요.** 메시지는 게이트웨이가 다시 쓸 수 있는 표시용
문자열입니다.

`createCall`은 통화가 만들어지기 전에 거부될 수도 있습니다. 이 경우
`call.created`도 `callId`도 과금도 없습니다. 게이트웨이는 재시도하지 않으므로
재시도 정책은 호출자 몫입니다.

| 게이트웨이 `code` | 예외 | 대응 |
| --- | --- | --- |
| `insufficientCredit` | `CallRefusedError` | 충전을 안내합니다. 재전송해도 소용없습니다 |
| `concurrentLimitExceeded` | `CallRefusedError` | 자기 통화가 하나 끝나기를 기다렸다가 재시도합니다 |
| `callerNotVerified` | `CallRefusedError` | 번호 인증을 안내합니다. 재전송해도 소용없습니다 |
| `noRepresentativeNumber` | `CallRefusedError` | 발신 번호 설정을 안내합니다. 재전송해도 소용없습니다 |
| `callProviderUnauthorized` | `CallProviderError` | 서비스 장애로 보고합니다. 재전송은 도움이 안 됩니다 |
| `callProviderDraining` | `CallProviderError` | 나중에 재시도합니다 |
| `callProviderUnavailable` | `CallProviderError` | 나중에 재시도합니다 |
| `callSetupFailed` | `CallProviderError` | 실패로 보고합니다 |

명령 단위 오류는 소켓을 닫지 않고 `EventType.ERROR` 구독자에게도 전달됩니다.
통화를 끝내는 오류는 그 통화의 `create_call`에 대한 오류뿐입니다.
`create_call`은 항상 `requestId`를 보내고(생략하면 생성) 게이트웨이가 오류
프레임에 그 값을 되돌려 주므로, SDK가 그 오류를 가려낼 수 있습니다. `answer`,
`send_dtmf`, `get_summary`, `cancel`의 오류는 통화를 끝내지 않습니다.
`EventType.ERROR` 이벤트로만 전달되고, `wait_closed()`는 통화의 종료 이벤트를
계속 기다립니다. 그러니 명령마다 `request_id`를 따로 주거나 생략하세요.
`create_call`의 requestId를 다른 명령에 다시 쓰면 그 명령의 오류가 대기를
끝내 버립니다. 실패한 `create_call`(예: `toRequired`, `callRejected`)이 멈춘
채 남지 않도록, `wait_closed()`가 그 오류를 다시 raise 합니다:

- 인증 실패(`unauthenticated`·`ipNotAllowed` 프레임, 4401 종료, `auth.ok` 타임아웃) → `connect()`가 `AuthenticationError` raise
- 인증 중 게이트웨이가 키를 확인하지 못함(`internalError` 프레임 또는 1011 종료) → `connect()`가 `TelloServerError` raise. 키가 거절된 것이 아니므로 잠시 뒤 다시 접속하면 됩니다
- `create_call` 오류(`call.created` 전의 거부, 또는 그 뒤의 실패) → 위 표의 대응 예외
- `callAlreadyActive` → `CallAlreadyActiveError`. 단, 통화를 시작한 `create_call`에 대한 응답일 때만입니다. 게이트웨이가 직전 통화를 아직 정리하는 중이라 이 통화는 시작되지 않았으니 잠시 뒤 다시 시도하세요. 통화 도중 보낸 `create_call`에 대한 응답이면 `EventType.ERROR` 이벤트일 뿐이고, 진행 중인 통화는 계속됩니다. `noActiveCall`로는 대기가 끝나지 않습니다
- 통화 도중 연결 끊김 → `ConnectionClosedError`
- 다른 연결에 세션을 빼앗김(4429 종료) → `SessionReplacedError`

`EventType.ERROR` 핸들러가 받는 것은 예외가 아니라 `ErrorEvent`입니다. 위 표의
타입별 예외로 바꾸려면 그 필드를 `tello.errors`의 `exception_for`에 넘기세요:

```python
from tello import CallRefusedError, EventType
from tello.errors import exception_for

@client.on(EventType.ERROR)
def on_error(event):
    error = exception_for(event.code, event.message, event.question)
    if isinstance(error, CallRefusedError):
        print(f"거부됨: {error.code}")
```

WS 수준 ping heartbeat는 게이트웨이가 주도하고, pong은 `websockets`가 알아서
보냅니다. 재연결이나 세션 재개 프로토콜은 없습니다. 비정상 종료가 나면 재연결이
필요한 상황으로 보고 통화를 처음부터 다시 시작하세요.

## 6. REST 자원 API (`TelloApi`)

`TelloApi`는 공개 REST API용 별도 클라이언트입니다. 도구·에이전트·크루
만들기·조회·수정·삭제, 에이전트·크루 목록, 목표로 크루 자동 생성, 통화 초안을
다룹니다. 새 의존성이 없습니다(표준 라이브러리 `urllib`을 이벤트 루프 밖에서
실행). 본문과 결과는 그냥 `dict[str, Any]`라서 SDK가 아직 모르는 칸도 잃지
않습니다.

```python
import asyncio
from tello import TelloApi, TelloApiError

async def main():
    api = TelloApi()  # TELLO_API_KEY(와 설정돼 있으면 TELLO_API_URL)를 읽습니다
    agents = await api.agents.list()
    tool = await api.tools.create(
        {"type": "endCall", "name": "통화 끝내기", "functionName": "end_call"},
        idempotency_key="tool-end-call-001",
    )
    await api.tools.update(tool["id"], {"description": "정중하게 통화를 끝냅니다"})

asyncio.run(main())
```

- **키**: `TelloApi(api_key=...)`, 없으면 `TELLO_API_KEY`(`TelloClient`와 같은
  규칙·같은 오류). `Authorization: Bearer <키>`로 보내며 `repr()`이나 오류
  메시지에는 절대 나오지 않습니다.
- **URL**: `api_url=...`, 없으면 `TELLO_API_URL`, 없으면 `https://api.telloai.io/v1`.
  `https`만 받습니다. `http`는 `127.0.0.1`·`localhost`·`::1`(테스트용)만 됩니다.
- **타임아웃**: 요청마다 30초, `crews.generate`와 `call_drafts` 세 요청은 120초.
  `timeout=` / `long_timeout=`(초)으로 바꿀 수 있습니다.
- **자동 재시도는 없습니다.** (같은 멱등 키로) 다시 보내는 것은 호출자 몫입니다.
- 모든 요청에 `User-Agent: tello-python-sdk/<버전>`을 붙입니다.

| 메서드 | HTTP | 성공 | 반환 |
| --- | --- | --- | --- |
| `tools.list(*, limit=None, cursor=None)` | `GET /tools` | 200 | `{"data": [...], "nextCursor": str \| None}` |
| `tools.get(id)` | `GET /tools/{id}` | 200 | 도구 |
| `tools.create(body, *, idempotency_key=None)` | `POST /tools` | 201 | 도구(`revision` 포함) |
| `tools.update(id, patch)` | `PATCH /tools/{id}` | 200 | 도구 |
| `tools.delete(id)` | `DELETE /tools/{id}` | 204 | `None` |
| `agents.list()` | `GET /agents` | 200 | `{"data": [{"id", "name", "description", "isDefault"}]}` |
| `agents.get` / `create` / `update` / `delete` | `/agents[/{id}]` | 200 / 201 / 200 / 204 | 에이전트 / `None` |
| `crews.list()` | `GET /crews` | 200 | `{"data": [...]}` |
| `crews.get` / `create` / `update` / `delete` | `/crews[/{id}]` | 200 / 201 / 200 / 204 | 크루 / `None` |
| `crews.generate(body, *, idempotency_key=None)` | `POST /crews/generate` | 202 (같은 목표의 기존 작업이면 200) | 작업 `{"id", "status": "running", ...}` |
| `crews.generate_and_wait(body, *, poll_interval=2.0, timeout=600.0, idempotency_key=None)` | generate 후 폴링 | — | 끝난 작업(`succeeded` 또는 `failed`) |
| `crew_generations.get(id)` | `GET /crew-generations/{id}` | 200 | 작업(`running` / `succeeded` / `failed`) |
| `call_drafts.create(body, *, idempotency_key=None)` | `POST /call-drafts` | 201 | 초안 |
| `call_drafts.revise(draft_id, request, *, idempotency_key=None)` | `POST /call-drafts/{id}/revise` `{"request": ...}` | 200 | **새 id**의 초안 |
| `call_drafts.confirm(draft_id, *, idempotency_key=None)` | `POST /call-drafts/{id}/confirm`(본문 없음) | 201 | 건 통화 |

> **쓰기는 즉시 운영에 반영됩니다.** 도구·에이전트·크루를 만들거나 고치거나
> 지우면(그리고 `crews.generate`도) 저장·배포·운영 반영까지 한 번에 되고, 다음
> 통화부터 그대로 쓰입니다. 임시 저장 단계는 없습니다.
>
> **`call_drafts.confirm`은 실제로 과금되는 전화를 겁니다.** `call_drafts.create`도
> 에이전트 시나리오가 준비돼 있으면 바로 걸 수 있습니다(`status` `confirmed`와
> `callId`). 초안 `status`(`pendingConfirmation`·`needsClarification`·`refused`·
> `confirmed`)는 모두 `201` 성공이고 오류가 아닙니다.

멱등 키는 `idempotency_key`를 준 때만 보냅니다(create·generate·초안 create/revise).
`call_drafts.confirm`은 항상 보냅니다. 준 키가 없으면 UUID v4를 만듭니다. 키는
1~255자의 출력 가능한 ASCII(0x20–0x7E)에 쉼표가 없어야 하며, 어기면 요청 없이 `ValueError`가 납니다.
빈 id도 같습니다. `generate_and_wait`는 `failed` 작업을 예외 없이 돌려주고
(`job["status"]`로 분기), `timeout`이 지나도 실행 중이면 작업 id를 담은
`TimeoutError`를 던집니다.

### REST 오류

오류 응답은 `TelloApiError`(`TelloError` 하위)로 던집니다. 칸은 `status`(HTTP),
`code`(봉투의 `error` 원문 snake_case), `message`, `data`(dict 또는 `None`),
`idempotency_key`(보낸 키, 없으면 `None`)입니다. 오류 봉투가 아닌 응답(프록시
페이지 등)은 `code = "http_<상태>"`, 문서에 없는 성공 상태나 JSON 객체가 아닌
본문은 `code = "invalid_response"`입니다. 응답을 못 받으면(연결 실패·타임아웃)
`idempotency_key`와 `__cause__`(원인)를 담은 `TelloApiConnectionError`가 납니다.
**이렇게 실패한 쓰기는 이미 반영됐을 수 있습니다.** 다시 보내기 전에
`get`/`list`로 확인하세요.

| HTTP | `code` | 의미 |
| --- | --- | --- |
| 401 | `unauthenticated` | 키가 없거나 잘못됐거나 폐기됨 |
| 403 | `insufficient_scope` | 키에 권한이 없음(`data.requiredScope`) |
| 404 | `tool_not_found` / `agent_not_found` / `crew_not_found` | 이 계정에 없는 항목 |
| 404 | `crew_generation_not_found` / `draft_not_found` | 없는 작업·초안 |
| 409 | `idempotency_key_reused` | 다른 요청에 이미 쓴 키 |
| 409 | `crew_generation_in_progress` | 다른 목표로 크루를 만드는 중(`data.id`) |
| 409 | `draft_already_confirmed` | 이미 확정한 초안(`data.callId`) |
| 502 | `write_outcome_unknown` | 반영됐을 수 있음. 확인한 뒤에만 새로 만드세요 |
| 503 | `upstream_unavailable` | 처리되지 않음. 잠시 뒤 다시 보내세요 |

전체 목록은 공개 REST 오류 문서에 있습니다. `message`가 아니라 `code`로 분기하세요:

```python
from tello import TelloApiConnectionError, TelloApiError

try:
    call = await api.call_drafts.confirm(draft_id)
except TelloApiError as e:
    if e.code == "draft_already_confirmed":
        print("이미 건 통화:", e.data["callId"])
    else:
        raise
except TelloApiConnectionError as e:
    # 전화가 걸렸을 수 있습니다. 새 키가 아니라 같은 키로 다시 보내세요.
    call = await api.call_drafts.confirm(draft_id, idempotency_key=e.idempotency_key)
```

## 7. 예제

바로 실행해 볼 수 있는 프로그램이 [`examples/`](examples/README.ko.md)에
있습니다:

```bash
uv run python examples/basic_call.py       # 연결, 통화 1건, 각 턴에 응답
uv run python examples/agent_callback.py   # 전체 수명주기, 이력, cancel, 타입별 오류
uv run python examples/call_summary.py     # 게이트로 막아 둔 라이브 시나리오 + call.summary
```

세 예제 모두 실제 통화를 겁니다. 먼저
[`examples/README.ko.md`](examples/README.ko.md)를 읽으세요.

## 8. 버전 호환성

`tello-ai-sdk 0.1.x`는 Tello WS 프로토콜 `1.0`을 구현합니다.

프레임 계약 전문은 [`docs/protocol/sdk-ws.v1.md`](docs/protocol/sdk-ws.v1.md)에
있고, [`docs/events/sdk-events.v1.schema.json`](docs/events/sdk-events.v1.schema.json)과
[`docs/errors/errors.v1.json`](docs/errors/errors.v1.json)이 함께 있습니다. 이
세 파일은 게이트웨이 구현 옆에 있는 정본에서 복사해 온 생성물입니다. 읽는 건
여기서, 고치는 건 정본에서 합니다.
