# Tello SDK WebSocket 프로토콜 계약 v1

> version: 1.0
> 대상: turn-provider-gateway `/sdk` 엔드포인트
> 상태: source of truth. 모든 언어 SDK는 이 문서와 `../events/sdk-events.v1.schema.json`, `../errors/errors.v1.json`을 기준으로 구현한다.

SDK는 이 WebSocket 하나로 통화를 시작하고, 상대방 발화(turn)를 받아 응답한다. REST/webhook은 이 프로토콜에 포함되지 않는다.

## 1. 엔드포인트 / 연결

```text
ws(s)://<host>:<port>/sdk
```

- 기본 포트 3000. WebSocket 서브프로토콜 협상 없음.
- 한 연결당 활성 통화는 하나다.

## 2. 인증 (애플리케이션 핸드셰이크)

인증은 HTTP upgrade 헤더나 쿼리 토큰이 아니라 **애플리케이션 프레임**으로 이뤄진다.
API key는 upgrade 요청, URL 쿼리, 로그, 예외 메시지 어디에도 노출되지 않는다.

1. 소켓이 열린 뒤 클라이언트가 보내는 **첫 프레임**은 반드시 `auth`다. raw API key는 `token` 필드로 보낸다.

   ```json
   { "event": "auth", "data": { "token": "<TELLO_API_KEY>", "requestId": "<optional>" } }
   ```

2. 서버가 `auth.ok`를 보내기 전에는 다른 어떤 명령도 보내면 안 된다.

   ```json
   { "type": "auth.ok", "version": "1.0", "accountId": "<accountId>", "requestId": "<echoed when supplied>" }
   ```

3. `auth.ok` 이후에만 `createCall` / `listAgents` / `answer` / `sendDtmf` / `cancel`
   / `getSummary` / `sendSms`를 보낼 수 있다.

인증 실패 시 서버는 `error` 프레임(`code: "unauthenticated"`)을 보내고 close code `4401`로
연결을 종료한다. `auth.ok`를 기다리는 타임아웃(서버 데드라인 5초) 역시 연결 실패로 취급한다.

## 3. 프레임 방향 비대칭 (중요)

- **아웃바운드(client → server)**: NestJS `@nestjs/platform-ws` 라우팅 봉투를 쓴다.

  ```json
  { "event": "<command>", "data": { "...": "..." } }
  ```

- **인바운드(server → client)**: 봉투 없이 **flat** 프레임이다. `type` 필드로 디스패치한다.

  ```json
  { "type": "<event>", "version": "1.0", "sessionId": "...", "callId": "...", "timestamp": "..." }
  ```

## 4. 명령 (client → server)

`data` 안의 필드다. 모든 명령은 선택적 `requestId`를 가질 수 있고, 실패 시 error 프레임의 `requestId`로 에코된다.

### 4.1 `createCall`

```json
{ "event": "createCall", "data": {
  "to": "+821012345678",          // 필수. 전화할 대상 번호. 비면 error: toRequired
  "agentId": "agent-1",           // 필수. 비면 error: agentIdRequired
  "prompt": "예약 확인",           // 선택, 기본 ""
  "metadata": { "any": "json" },  // 선택
  "requestId": "req-1"            // 선택
}}
```

이미 활성 통화가 있으면 error `callAlreadyActive`.

### 4.2 `answer`

```json
{ "event": "answer", "data": {
  "text": "확인했습니다.",         // 선택, 기본 ""
  "messageId": "m1",             // 선택, 기본 서버 생성 UUID
  "requestId": "req-2"           // 선택
}}
```

활성 통화가 없으면 error `noActiveCall`. 성공 시 동일한 `requestId`(제공한 경우)와
유효 `messageId`를 담은 `answer.accepted`가 먼저 오며, 답변이 실제 통화에 반영되면
후속 `agent.turn` 이벤트가 온다.

### 4.3 `sendDtmf`

```json
{ "event": "sendDtmf", "data": {
  "digits": "1234#",             // 필수. 보낼 DTMF 다이얼 문자열
  "messageId": "m1",             // 선택, 기본 서버 생성 UUID
  "requestId": "r1"              // 선택
}}
```

`answer`를 미러링하는 명령이며, `text` 대신 `digits`를 보낸다. `digits`는 키패드
문자 `0-9`, `*`, `#`만 허용한다. 활성 통화가 없으면 error `noActiveCall`, `digits`가
비면 `dtmfDigitsRequired`, 허용 문자 외가 섞이면 `dtmfDigitsInvalid`.

### 4.4 `cancel`

```json
{ "event": "cancel", "data": {} }
```

활성 통화가 없으면 무시(no-op).

## 5. 이벤트 (server → client)

스키마: `../events/sdk-events.v1.schema.json`. 공통 필드 `type`, `version` ("1.0"), `sessionId`, `callId`, `timestamp`(ISO-8601). 필드는 camelCase.

| type | 추가 필드 | 의미 |
| --- | --- | --- |
| `call.created` | — | createCall 직후 첫 프레임. 공통 `callId`로 통화 id를 즉시 전달 |
| `call.statusChanged` | `status`, `previousStatus` | 통화 상태 전이. cancelled도 이 이벤트(status `"cancelled"`)로 온다 |
| `user.turn` | `turnIndex`, `text` | 상대방 발화. SDK가 응답할 차례 |
| `answer.accepted` | `requestId?`, `messageId` | answer 명령이 검증되어 Voice Gateway로 제출됨. 실제 발화는 후속 `agent.turn`으로 확인 |
| `dtmf.accepted` | `requestId?`, `messageId`, `digits` | sendDtmf 명령이 검증되어 Voice Gateway로 제출됨 |
| `agent.turn` | `turnIndex`, `text` | SDK 답변이 통화로 반영됨 |
| `call.completed` | `status` | 종단: 정상 완료 |
| `call.noAnswer` | `status`, `failureReason?` | 종단: 무응답 |
| `call.failed` | `status`, `failureReason?` | 종단: 실패 |

status 어휘: `queued`, `dialing`, `ringing`, `inProgress`, `transferring`, `completed`, `noAnswer`, `failed`, `cancelled`.

종단 이벤트(`call.completed`/`call.noAnswer`/`call.failed`, 또는 cancelled statusChanged) 이후 서버는 해당 통화 스트림을 종료한다.

## 6. 에러 프레임

스키마: `../errors/errors.v1.json`. 별도 봉투 없이 flat이다.

```json
{ "type": "error", "version": "1.0", "code": "noActiveCall", "message": "No active call", "requestId": "req-2" }
```

| code | 기본 message | 비고 |
| --- | --- | --- |
| `unauthenticated` | Authentication required | 연결 시 발생, close 4401 동반 |
| `callAlreadyActive` | A call is already active | |
| `toRequired` | to is required | |
| `agentIdRequired` | agentId is required | |
| `callIdRequired` | callId is required | `getSummary`에 `callId` 누락 |
| `callNotFound` | Call not found | `getSummary` 대상 통화 없음 |
| `callNotCompleted` | Call is not completed | `getSummary` 통화가 아직 미완료 |
| `smsToRequired` | SMS recipient is required | `sendSms`에 `to` 누락 |
| `smsMessageRequired` | SMS message is required | `sendSms`에 `message` 누락 |
| `smsFailed` | SMS send failed | `sendSms` 전송 실패 |
| `noActiveCall` | No active call | |
| `dtmfDigitsRequired` | digits is required | `sendDtmf`에 `digits` 누락 |
| `dtmfDigitsInvalid` | digits must contain only 0-9, *, # | `sendDtmf` `digits`에 허용 외 문자 |
| `callRejected` | Call rejected | `question` 필드 동반 가능 |
| `internalError` | Internal error | `message`에 상세 사유 |

명령 실패 error는 연결을 닫지 않는다.

## 7. Close code

| code | 이름 | 사용 |
| --- | --- | --- |
| 1000 | Normal | 정상 종료 |
| 4401 | Unauthenticated | 연결 인증 실패 (현재 실제 방출되는 유일한 코드) |

heartbeat 타임아웃으로 인한 종료는 close 프레임 없이 소켓이 끊긴다(`terminate()`).

## 8. 하트비트

서버가 30초마다 **WebSocket 프로토콜 ping**을 보낸다. 클라이언트는 표준 **pong**으로 응답해야 한다(직전 ping에 pong이 없으면 다음 sweep에서 연결이 끊긴다). 앱 레벨 JSON 하트비트가 아니므로 표준 WS 라이브러리(예: Python `websockets`)는 자동으로 처리한다.

## 9. 비목표

- 재연결 / 세션 resume 프로토콜 없음.
- `answer.accepted`는 명령 제출 ACK일 뿐 실제 발화 전달 보장은 아니다. 실제 통화
  반영은 후속 `agent.turn`으로 확인한다.
