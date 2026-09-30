[English](README.md) | **한국어**

# tello-ai-sdk (Python)

> 저장소: `tello-python` · PyPI 배포명: `tello-ai-sdk` · import: `tello`

Python용 Tello SDK. turn-provider-gateway `/sdk` 엔드포인트에 붙는 얇은
**WebSocket** 실시간 클라이언트입니다. SDK가 대화의 두뇌를 맡습니다.
게이트웨이는 진행 중인 통화에서 상대방이 말한 턴을 실시간으로 넘겨주고,
핸들러가 만든 답변은 다시 통화로 전달됩니다.

> 전송 계층은 WebSocket뿐입니다. REST나 webhook은 제공하지 않습니다. 프로토콜
> 계약은 [`docs/protocol/sdk-ws.v1.md`](docs/protocol/sdk-ws.v1.md)에 있습니다.

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
export TELLO_URL="ws://localhost:3000/sdk"   # 선택. 기본값 ws://localhost:3000/sdk
```

인자 없이 `TelloClient()`를 호출하면 `TELLO_API_KEY` / `TELLO_URL`을 읽습니다.

## 3. 연결 + 통화 시작

```python
import asyncio
from tello import TelloClient, EventType

async def main():
    async with TelloClient(api_key="tello_live_xxx", url="ws://localhost:3000/sdk") as client:
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
client = TelloClient(api_key="tello_live_xxx", url="ws://localhost:3000/sdk")
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
`await client.answer(text, message_id=None)`,
`await client.send_dtmf(digits, message_id=None)`, `await client.cancel()`,
`await client.get_summary(call_id, request_id=None)`. `create_call`은 항상
`requestId`를 보냅니다. 직접 넘긴 값을 쓰고, 생략하면 UUID를 생성해 씁니다.

`await client.wait_closed()`는 통화가 종료 상태(`call.completed` /
`call.noAnswer` / `call.failed`, 또는 cancelled 상태)에 이르거나 연결이 닫히면
resolve 됩니다. 통화의 `create_call`이 실패하면 대신 오류를 raise 합니다(§5
참고). 다른 명령의 오류로는 대기가 끝나지 않습니다.

## 5. 오류 처리

게이트웨이 오류 프레임은 예외와 1:1로 대응됩니다
([`docs/errors/errors.v1.json`](docs/errors/errors.v1.json) 참고):

| 게이트웨이 `code` | 예외 |
| --- | --- |
| `unauthenticated` | `AuthenticationError` (인증 핸드셰이크. 4401 종료 포함) |
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
계속 기다립니다. 실패한 `create_call`(예: `toRequired`, `callRejected`)이 멈춘
채 남지 않도록, `wait_closed()`가 그 오류를 다시 raise 합니다:

- 인증 실패(`unauthenticated` 프레임, 4401 종료, `auth.ok` 타임아웃) → `connect()`가 `AuthenticationError` raise
- `create_call` 오류(`call.created` 전의 거부, 또는 그 뒤의 실패) → 위 표의 대응 예외. `callAlreadyActive`는 대기를 끝내지 않습니다. 이미 진행 중인 통화가 계속됩니다
- 통화 도중 연결 끊김 → `ConnectionClosedError`
- 다른 연결에 세션을 빼앗김(4429 종료) → `SessionReplacedError`

WS 수준 ping heartbeat는 게이트웨이가 주도하고, pong은 `websockets`가 알아서
보냅니다. 재연결이나 세션 재개 프로토콜은 없습니다. 비정상 종료가 나면 재연결이
필요한 상황으로 보고 통화를 처음부터 다시 시작하세요.

## 6. 예제

바로 실행해 볼 수 있는 프로그램이 [`examples/`](examples/README.ko.md)에
있습니다:

```bash
uv run python examples/basic_call.py       # 연결, 통화 1건, 각 턴에 응답
uv run python examples/agent_callback.py   # 전체 수명주기, 이력, cancel, 타입별 오류
uv run python examples/call_summary.py     # 게이트로 막아 둔 라이브 시나리오 + call.summary
```

세 예제 모두 실제 통화를 겁니다. 먼저
[`examples/README.ko.md`](examples/README.ko.md)를 읽으세요.

## 7. 버전 호환성

`tello-ai-sdk 0.1.x`는 Tello WS 프로토콜 `1.0`을 구현합니다.

프레임 계약 전문은 [`docs/protocol/sdk-ws.v1.md`](docs/protocol/sdk-ws.v1.md)에
있고, [`docs/events/sdk-events.v1.schema.json`](docs/events/sdk-events.v1.schema.json)과
[`docs/errors/errors.v1.json`](docs/errors/errors.v1.json)이 함께 있습니다. 이
세 파일은 게이트웨이 구현 옆에 있는 정본에서 복사해 온 생성물입니다. 읽는 건
여기서, 고치는 건 정본에서 합니다.
