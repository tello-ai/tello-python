# Tello SDK 디렉터리 및 아키텍처 버전관리 가이드

> 참고: 이 문서는 4개 언어 SDK 공통 구조/버전관리 스펙의 사본이다. 이 리포(`tello-python`)에서 프로토콜 계약은 [`docs/protocol/sdk-ws.v1.md`](protocol/sdk-ws.v1.md), 스키마는 [`docs/events`](events)·[`docs/errors`](errors)에 있다. 아래 `sdk/contracts/...` 경로 표기는 공통 모노레포 기준이다.
>
> 작성일: 2026-06-29 (WS-only 재정리: 2026-07-07)
> 목적: Tello SDK를 Python / Node.js / Java / Go 중심으로 만들 때의 폴더 구조, 책임 경계, 버전관리 기준을 정리한다.
> 상태: Locked. 초기 공식 SDK는 Python / Node.js / Java / Go로 고정한다.
> 전송: **WebSocket 전용.** SDK는 turn-provider-gateway의 `/sdk` WebSocket 엔드포인트로만 붙는다. REST 호출, 콜백 HTTP 서버, 웹훅(HMAC) 방식은 이 SDK의 범위가 아니다.
> 참고: ClawOps Node.js SDK, ClawOps Python SDK 구조를 비교 참고했다. 프로토콜 계약의 원천은 `sdk/contracts/`와 turn-provider-gateway 구현이다.

참조 URL:

- https://github.com/learners-superpumped/clawops-node
- https://github.com/learners-superpumped/clawops-node/blob/main/package.json
- https://github.com/learners-superpumped/clawops-python
- https://github.com/learners-superpumped/clawops-python/blob/main/pyproject.toml

---

## 1. 기본 방향

SDK는 Tello의 전화 인프라, STT, TTS, 통화 상태 이벤트를 개발자 서버에서 쉽게 쓰게 하는 얇은 클라이언트 계층이다. 개발자 앱은 gateway와 **하나의 WebSocket 연결**을 열고, 그 위에서 통화를 시작하고 상대방 발화(turn)를 받아 응답한다.

SDK 책임:

- WebSocket 연결 인증(연결 시 Bearer API key)과 프레임 직렬화/역직렬화
- 통화 시작(`create_call`), 취소(`cancel`)
- 실시간 turn 이벤트(`user.turn` 등) 수신 및 pub/sub 디스패치
- 응답 텍스트 전송(`answer`)
- 하트비트 pong 응답, 타임아웃, 에러 타입 정리
- 예제와 테스트 제공

SDK가 하지 말아야 할 일:

- 가입자 AI 로직 내장
- Tello 서버의 상태 저장 복제
- 특정 LLM 벤더 종속
- 포털 UI 로직 포함
- 통화 정책 임의 판단

핵심 경계:

```text
Tello 서버 = 전화 인프라 + 세션 상태 + STT/TTS 실행 + turn-provider-gateway(/sdk WS)
SDK       = 가입자 코드에서 gateway WS에 붙어 통화 turn을 주고받는 클라이언트
가입자 앱  = AI 판단, 업무 시스템 연동, 대화 정책
```

---

## 2. 권장 최상위 구조

SDK는 repo 루트에 `sdk/`로 분리한다.

ClawOps 참고 반영:

- Node SDK는 `src/`, `tests/`, `docs/`, `package.json`, `tsup`, `vitest`, `exports` 구조가 적합하다.
- Node SDK는 realtime WS 기본 API와 agent runtime을 subpath export로 나눌 수 있다.
- Python SDK는 `src/{package}`, `tests`, `docs`, `pyproject.toml`, Hatch 기반 구조가 적합하다.
- Python SDK는 optional dependency extras로 agent/provider 기능을 분리하는 방식이 좋다.
- Tello도 초기 모노레포에서는 같은 구조를 유지하고, 공개 배포 전 언어별 repo로 분리한다(예: `tello-python`, `tello-node`).

```text
office-sdk/
  docs/
  architecture/
  sdk/
    .github/
      workflows/
        sdk-test.yml
        sdk-release.yml
        sdk-patch-release.yml
    README.md
    CHANGELOG.md
    VERSION
    contracts/
      protocol/
        sdk-ws.v1.md          # WS 프로토콜 계약(엔드포인트/인증/명령/이벤트/에러/heartbeat)
      events/
        sdk-events.v1.schema.json
      errors/
        errors.v1.json
    packages/
      python/
        pyproject.toml
        README.md
        docs/
        src/
          tello/
            __init__.py
            _version.py
            py.typed
            client.py           # WS 연결 수명주기 + 명령 전송 + 인바운드 디스패치
            realtime.py         # pub/sub 이벤트 핸들러 + answer
            events.py           # 인바운드 flat 프레임 파서 + EventType
            commands.py         # 아웃바운드 {event,data} 봉투 빌더
            errors.py
            types.py
            config.py
            agent/
              __init__.py
              runtime.py
              tools.py
        tests/
          test_client.py
          test_events.py
          test_realtime.py
        examples/
          basic_call.py
          agent_callback.py
      node/
        package.json
        tsconfig.json
        tsup.config.ts
        vitest.config.ts
        README.md
        docs/
        src/
          index.ts
          client.ts
          calls.ts
          realtime.ts
          errors.ts
          types.ts
          config.ts
          agent/
            index.ts
            runtime.ts
            tools.ts
        tests/
          client.test.ts
          events.test.ts
          realtime.test.ts
        examples/
          basic-call.ts
          agent-callback.ts
      java/
        build.gradle.kts
        README.md
        src/
          main/
            java/
              ai/
                tello/
                  TelloClient.java
                  calls/
                    CallsClient.java
                  realtime/
                    RealtimeClient.java
                    TurnHandler.java
                  errors/
                    TelloException.java
                  model/
                    Call.java
                    TurnEvent.java
          test/
            java/
              ai/
                tello/
                  TelloClientTest.java
                  EventsTest.java
                  RealtimeClientTest.java
        examples/
          spring-boot-agent/
          basic-call/
      go/
        go.mod
        README.md
        tello/
          client.go
          calls.go
          realtime.go
          errors.go
          types.go
          config.go
        tello_test/
          client_test.go
          events_test.go
          realtime_test.go
        examples/
          basic-call/
          agent-callback/
    examples/
      python-fastapi/
      node-express/
      nextjs-api-route/
      java-spring-boot/
      go-http-server/
    scripts/
      generate-types.sh
      verify-contracts.sh
      release-python.sh
      release-node.sh
      release-java.sh
      release-go.sh
```

`sdk/contracts/`가 기준이다. Python / Node / Java / Go SDK는 이 WS 프로토콜 계약을 보고 타입과 프레임 코드를 맞춘다.

Node와 Python은 ClawOps처럼 기본 realtime SDK와 agent runtime을 분리한다.

```text
Node:
  @tello/sdk        -> realtime WS 기본 SDK
  @tello/sdk/agent  -> agent runtime

Python:
  tello-python      -> 언어별 repo 이름
  tello-sdk         -> PyPI 배포명
  import tello      -> Python import namespace
  tello-sdk[agent]  -> agent runtime dependencies 포함
```

---

## 3. contracts 구조

### 3.1 WS 프로토콜 계약

SDK는 turn-provider-gateway의 `/sdk` WebSocket 엔드포인트에만 붙는다. REST OpenAPI는 이 SDK 범위가 아니다. 프로토콜 계약은 하나의 문서로 관리한다.

```text
sdk/contracts/protocol/sdk-ws.v1.md
```

포함 대상:

- 엔드포인트: `ws(s)://<host>:<port>/sdk`
- 연결 인증: 소켓 오픈 후 첫 프레임으로 `{"event":"authenticate","data":{"apiKey":...}}`를 보내고 `auth.ok`를 기다린다(upgrade 헤더/쿼리 토큰 사용 안 함). 실패 시 `unauthenticated` error 프레임 또는 close code `4401`
- 프레임 방향 비대칭:
  - 아웃바운드(client→server): `{"event":"<command>","data":{...}}`
  - 인바운드(server→client): flat `{"type":"<event>","version":"1.0", ...}`
- 명령: `create_call` / `answer` / `cancel`
- 이벤트: `call.statusChanged` / `user.turn` / `agent.turn` / `call.completed` / `call.noAnswer` / `call.failed`
- 에러 프레임과 close code
- 하트비트(서버 ping → 클라 pong)

이 계약 문서와 아래 JSON Schema가 SDK 타입 생성의 기준이다. SDK별 수동 타입 정의는 최소화한다.

### 3.2 이벤트 스키마

인바운드 WS 이벤트는 JSON Schema로 관리한다.

```text
sdk/contracts/events/sdk-events.v1.schema.json
```

예시(상대방 발화 turn):

```json
{
  "type": "user.turn",
  "version": "1.0",
  "sessionId": "session_123",
  "callId": "call_123",
  "turnIndex": 1,
  "text": "예약 확인하려고 전화했습니다.",
  "timestamp": "2026-06-29T10:00:00Z"
}
```

필드는 camelCase이며 모든 이벤트는 `type`, `version`, `sessionId`, `callId`, `timestamp`를 공통으로 갖는다. 이벤트 `type` 추가는 허용한다. 기존 필드 삭제, 타입 변경, 의미 변경은 금지한다.

### 3.3 에러 스키마

SDK 에러 처리는 gateway 에러 코드와 1:1로 맞춘다.

```text
sdk/contracts/errors/errors.v1.json
```

에러는 별도 봉투 없이 flat 프레임으로 온다(`{"error":{...}}` 형태가 아님).

```json
{
  "type": "error",
  "version": "1.0",
  "code": "noActiveCall",
  "message": "No active call",
  "requestId": "req_123"
}
```

`code` 목록: `unauthenticated`, `callAlreadyActive`, `toRequired`, `agentIdRequired`, `noActiveCall`, `callRejected`, `internalError`. `requestId`는 클라이언트가 명령에 `requestId`를 넣었을 때만 에코된다. `callRejected`는 `question` 필드를 동반할 수 있다.

---

## 4. SDK 내부 모듈 책임

### 4.1 `client`

연결 인증(내부 `authenticate`/`auth.ok` 핸드셰이크), gateway URL, timeout, WS 연결 수명주기와 인바운드 프레임 디스패치 담당.

```python
from tello import TelloClient

async with TelloClient(api_key="tello_live_xxx", url="ws://localhost:3000/sdk") as client:
    ...
```

### 4.2 통화 제어

통화 제어는 `TelloClient`의 `create_call` / `answer` / `cancel` 명령으로 직접 한다. REST 통화 관리(list/get/summary 등)는 지원하지 않는다.

```python
await client.create_call(to="+821012345678", agent_id="agent-1", prompt="예약 확인")
# ...
await client.cancel()
```

### 4.3 `realtime`

turn 이벤트를 pub/sub으로 수신하고 응답 텍스트를 `answer`로 보낸다.

```python
@client.on(EventType.USER_TURN)
async def on_user_turn(event):
    await client.answer(text=my_agent.respond(event.text))
```

전송은 WebSocket 전용이다. 단순 폴링은 MCP 도구용으로만 유지하고 SDK에는 포함하지 않는다.

### 4.4 `errors`

gateway 에러 코드를 SDK 예외 타입으로 1:1 매핑한다.

| gateway `code` | SDK 예외 |
| --- | --- |
| `unauthenticated` | `AuthenticationError` |
| `toRequired` | `ValidationError` |
| `agentIdRequired` | `ValidationError` |
| `callAlreadyActive` | `CallAlreadyActiveError` |
| `noActiveCall` | `NoActiveCallError` |
| `callRejected` | `CallRejectedError` (`question` 포함) |
| `internalError` | `TelloServerError` |

연결 인증 실패 close(`4401`)도 `AuthenticationError`로 매핑한다.

---

## 5. 아키텍처 경계

SDK 방식 호출 흐름:

```text
가입자 앱
  ↓ SDK (outbound WS)
turn-provider-gateway /sdk
  ↓
VGW
  ↓
전화망 + STT + TTS
```

실시간 대화 흐름:

```text
상대방 발화
  ↓
VGW STT
  ↓
turn-provider-gateway
  ↓ user.turn 이벤트 (WS)
SDK pub/sub 핸들러
  ↓ 가입자 AI 응답 생성
SDK answer() (WS)
  ↓
Tello TTS
  ↓
상대방에게 음성 출력
```

서버별 책임:

| 영역 | 책임 |
| --- | --- |
| VGW | 전화 연결, STT/TTS, 통화 세션 실행 |
| turn-provider-gateway | SDK용 `/sdk` WS 전송 브리지, API 인증 |
| Portal | 가입자 설정, 키 발급, 사용량 확인 |
| SDK | 개발자 앱에서 gateway WS에 붙는 클라이언트 라이브러리 |

SDK는 서버 내부 구현을 직접 import하지 않는다. 외부 계약은 **WS 명령/이벤트 프레임**뿐이다.

---

## 6. 버전관리 원칙

버전은 3개 층으로 나눈다.

```text
프로토콜 버전  = WS 프레임의 version 필드 ("1.0")
Contract 버전  = protocol 문서 / event schema 버전
SDK 버전       = Python / Node / Java / Go 패키지 SemVer
```

### 6.1 프로토콜 버전

WS 프레임은 `version` 필드로 프로토콜 버전을 나타낸다.

```json
{ "type": "user.turn", "version": "1.0", "...": "..." }
```

규칙:

- breaking change는 major version(`"2.0"`)으로 분리
- 이벤트 필드 추가, 새 이벤트 `type` 추가는 허용
- 기존 필드 삭제, 타입 변경, 의미 변경은 금지
- 필수 명령 필드 추가는 breaking change

### 6.2 Contract 버전

계약 파일은 major version을 파일명에 포함한다.

```text
sdk-ws.v1.md
sdk-events.v1.schema.json
errors.v1.json
```

minor / patch 변경은 파일 내부 버전 표기(`$id` 또는 문서 상단 버전)에 기록한다.

### 6.3 SDK 버전

SDK 패키지는 SemVer를 따른다.

```text
MAJOR.MINOR.PATCH
```

| 변경 | 버전 |
| --- | --- |
| 기존 코드 깨짐 | MAJOR |
| 새 기능 추가, 하위호환 유지 | MINOR |
| 버그 수정, 문서 수정 | PATCH |
| 실험 기능 | prerelease |

SDK 버전은 기본적으로 같이 간다.

권장 정책:

```text
tello-sdk 1.4.0
@tello/sdk 1.4.0
ai.tello:tello-sdk 1.4.0
github.com/tello-ai/tello-sdk-go v1.4.0
```

이유:

- 고객 문서가 단순해진다.
- 호환성 문의가 줄어든다.
- contract 기준 릴리스가 쉬워진다.
- 언어별 기능 차이를 빨리 발견할 수 있다.

예외:

- 특정 언어만 빌드/패키징 버그가 있으면 patch만 따로 낼 수 있다.
- 예: `tello-sdk 1.4.1`, 나머지는 `1.4.0`.
- 기능 추가 minor는 모든 SDK가 준비됐을 때 같이 올린다.
- breaking change major도 모든 SDK가 같이 올린다.

즉, minor/major는 lockstep, patch는 언어별 예외 허용.

---

## 7. 호환성 매트릭스

`sdk/README.md` 또는 `sdk/VERSION`에 호환성 표를 둔다.

```text
SDK Version | Protocol Version | Contract Version | Status
----------- | ---------------- | ---------------- | ------
1.x         | 1.0              | contracts v1     | stable
2.x         | 2.0              | contracts v2     | future
```

패키지별 README에도 동일 정보를 둔다.

```text
tello-sdk 1.4.x supports Tello WS protocol 1.0.
@tello/sdk 1.4.x supports Tello WS protocol 1.0.
ai.tello:tello-sdk 1.4.x supports Tello WS protocol 1.0.
github.com/tello-ai/tello-sdk-go v1.4.x supports Tello WS protocol 1.0.
```

---

## 8. 릴리스 정책

릴리스 순서:

```text
1. contracts 변경
2. 서버 API 구현
3. contract test 통과
4. Python SDK 반영
5. Node SDK 반영
6. Java SDK 반영
7. Go SDK 반영
8. examples 갱신
9. CHANGELOG 작성
10. 패키지 publish
```

초기 브랜치 전략은 단순하게 유지한다.

```text
main
release/sdk-v1.x
```

권장 태그:

```text
sdk-v1.0.0
sdk-python-v1.0.0
sdk-node-v1.0.0
sdk-java-v1.0.0
sdk-go-v1.0.0
contracts-v1.0.0
```

일반 릴리스는 `sdk-v1.0.0` 태그로 묶고, 패키지별 publish 추적이 필요하면 언어별 태그를 추가한다.

CHANGELOG 위치:

```text
sdk/CHANGELOG.md
sdk/packages/python/CHANGELOG.md
sdk/packages/node/CHANGELOG.md
sdk/packages/java/CHANGELOG.md
sdk/packages/go/CHANGELOG.md
```

---

## 9. 배포 전략

모노레포를 source of truth로 둔다. 배포는 각 언어 생태계에 맞춰 따로 나간다.

```text
source repo
  sdk/contracts/
  sdk/packages/python/
  sdk/packages/node/
  sdk/packages/java/
  sdk/packages/go/
    ↓
publish targets
  PyPI
  npm
  Maven Central
  Go module tags / GitHub Release
```

공개 배포 단계에서는 ClawOps처럼 언어별 repo를 분리하는 구조를 권장한다.

```text
tello-sdk-contracts -> WS 프로토콜 계약, JSON Schema, error catalog
tello-sdk-node      -> npm package: @tello/sdk
tello-python        -> PyPI package: tello-sdk
tello-sdk-java      -> Maven package: ai.tello:tello-sdk
tello-sdk-go        -> Go module: github.com/tello-ai/tello-sdk-go
```

초기 내부 개발:

```text
office-sdk/sdk = contracts + 4개 SDK 모노레포
```

public beta 전:

```text
office-sdk/sdk/packages/node   -> tello-sdk-node
office-sdk/sdk/packages/python -> tello-python
office-sdk/sdk/packages/java   -> tello-sdk-java
office-sdk/sdk/packages/go     -> tello-sdk-go
office-sdk/sdk/contracts       -> tello-sdk-contracts
```

분리 이유:

- 고객이 언어별 SDK repo를 찾기 쉽다.
- Go import path가 짧고 안정적이다.
- npm/PyPI/Maven/Go release note를 독립 관리할 수 있다.
- 언어별 issue와 maintainer 권한을 나눌 수 있다.
- ClawOps처럼 Node/Python package repo를 독립 운영하는 방식과 맞다.

### 9.1 패키지별 배포 대상

| SDK | 배포 대상 | 방식 |
| --- | --- | --- |
| Python | PyPI | `python -m build`, `twine upload` 또는 trusted publishing |
| Node.js | npm | `npm publish --provenance` |
| Java | Maven Central | Gradle `publish`, GPG signing, Sonatype release |
| Go | Go module | git tag 기반. 필요 시 GoReleaser로 GitHub Release 생성 |

Go는 npm/PyPI처럼 registry에 업로드하지 않는다. 사용자가 `go get`을 실행하면 Go proxy가 git tag를 보고 module을 가져간다.

```bash
go get github.com/tello-ai/tello-sdk-go@v1.4.0
```

### 9.2 모노레포와 Go module 처리

Go SDK를 모노레포 하위 경로에 둘 경우 import path가 길어진다.

```text
github.com/tello-ai/office-sdk/sdk/packages/go
```

이 구조에서는 Go tag도 하위 디렉터리 prefix가 필요하다.

```text
sdk/packages/go/v1.4.0
```

고객이 쓰기 좋은 import path를 원하면 Go SDK는 별도 public mirror repo를 권장한다.

```text
github.com/tello-ai/tello-sdk-go
```

권장 운영:

```text
office-sdk monorepo = contracts + 모든 SDK source of truth
tello-sdk-go repo  = Go SDK publish mirror
```

GoReleaser는 이 mirror repo에서 사용한다.

GoReleaser 역할:

- tag 검증
- changelog 생성
- GitHub Release 생성
- archive/checksum 생성
- CLI 또는 예제 바이너리가 생길 경우 binary release

순수 Go library만 있으면 GoReleaser는 필수는 아니다. 하지만 release note와 tag 자동화 용도로 쓰면 좋다.

### 9.3 lockstep 릴리스

minor / major는 한 태그로 묶는다.

```text
sdk-v1.4.0
```

이 태그에서 CI가 4개 publish job을 실행한다.

```text
publish-python -> PyPI
publish-node   -> npm
publish-java   -> Maven Central
publish-go     -> Go tag / GitHub Release
```

각 패키지 manifest의 version은 모두 `1.4.0`으로 맞춘다.

```text
sdk/VERSION                          = 1.4.0
sdk/packages/python/pyproject.toml   = 1.4.0
sdk/packages/node/package.json       = 1.4.0
sdk/packages/java/build.gradle.kts   = 1.4.0
sdk/packages/go/go.mod               = module path 고정, 버전은 git tag로 관리
```

### 9.4 patch 릴리스

언어별 버그만 고칠 때는 해당 SDK만 patch 배포한다.

예:

```text
tello-sdk 1.4.1
@tello/sdk 1.4.0
ai.tello:tello-sdk 1.4.0
github.com/tello-ai/tello-sdk-go v1.4.0
```

태그:

```text
sdk-python-v1.4.1
```

Go patch라면:

```text
sdk-go-v1.4.1
```

Go mirror repo에는:

```text
v1.4.1
```

patch는 contract 변경 없이 진행한다. contract 변경이 있으면 minor 이상으로 올리고 전체 SDK lockstep 릴리스로 처리한다.

### 9.5 CI/CD 권장 구조

GitHub Actions 기준:

```text
.github/workflows/sdk-test.yml
  - PR마다 contracts + 4개 SDK test 실행

.github/workflows/sdk-release.yml
  - sdk-v* 태그에서 전체 SDK 배포

.github/workflows/sdk-patch-release.yml
  - sdk-python-v* / sdk-node-v* / sdk-java-v* / sdk-go-v* 태그에서 해당 SDK만 배포
```

배포 job은 순서를 나눈다.

```text
1. verify-contracts
2. test-python
3. test-node
4. test-java
5. test-go
6. publish-python
7. publish-node
8. publish-java
9. publish-go
10. create-github-release
```

publish는 tag에서만 실행한다. main push에서는 테스트만 실행한다.

---

## 10. Breaking Change 기준

major version 변경 대상:

- public method 이름 변경
- public method parameter 삭제 또는 필수화
- 반환 타입 변경
- 이벤트 필드 삭제
- 이벤트 필드 타입 변경
- 에러 코드 삭제 또는 의미 변경
- 인증 방식 변경
- 기본 timeout / retry 동작이 기존 앱 흐름을 깨는 변경

minor 변경 가능:

- optional parameter 추가
- response field 추가
- 새 이벤트 type 추가
- 새 helper method 추가
- 새 example 추가

patch 변경 가능:

- 버그 수정
- 타입 정확도 개선
- 문서 보완
- 내부 리팩터링
- 테스트 추가

---

## 11. 실험 기능 관리

초기 SDK의 실험 기능은 stable API와 분리한다.

```text
tello.experimental.realtime_low_latency
tello.experimental.agent_session
```

규칙:

- `experimental` namespace 아래에만 둔다.
- README에 안정성 보장 안 함을 명시한다.
- stable 승격 시 이름과 계약을 다시 확정한다.
- experimental 기능 제거는 major 없이 가능하되 changelog에 기록한다.

---

## 12. 테스트 기준

SDK 릴리스 전 최소 테스트:

- `authenticate` 프레임을 첫 프레임으로 전송하고 `auth.ok`까지 대기
- 인증 실패(`unauthenticated` 프레임 / close 4401 / `auth.ok` 타임아웃) → AuthenticationError 매핑
- 명령 프레임 봉투(`{event,data}`) 직렬화 검증
- 인바운드 flat 이벤트 프레임 parse
- 에러 프레임 code → 예외 매핑 (`requestId` 에코 포함)
- 하트비트 pong 응답(연결 유지)
- pub/sub 핸들러 디스패치(동기·비동기)
- contract fixture 호환성

Contract test 기준:

```text
contracts fixture -> Python SDK parse OK
contracts fixture -> Node SDK parse OK
contracts fixture -> Java SDK parse OK
contracts fixture -> Go SDK parse OK
server event frame -> sdk-events.v1 schema validate OK
```

---

## 13. 문서 기준

각 SDK README는 같은 구조를 유지한다.

```text
1. 설치
2. API key 설정
3. 연결 + 첫 통화 시작
4. 실시간 turn 이벤트 처리 (pub/sub)
5. 에러 처리
6. 버전 호환성
```

최소 예제:

```python
import asyncio
from tello import TelloClient, EventType

async def main():
    async with TelloClient(api_key="tello_live_xxx", url="ws://localhost:3000/sdk") as client:
        @client.on(EventType.USER_TURN)
        async def on_user_turn(event):
            await client.answer(text="확인했습니다. 계속 말씀해주세요.")

        await client.create_call(to="+821012345678", agent_id="agent-1", prompt="예약 확인")
        await client.wait_closed()

asyncio.run(main())
```

---

## 14. 초기 구현 추천 순서

첫 버전은 작게 낸다.

```text
v0.1.0
  - WS 연결 + 인증(authenticate/auth.ok 핸드셰이크)
  - create_call() / answer() / cancel()
  - turn 이벤트 pub/sub (user.turn / agent.turn / call.statusChanged / call.*)
  - 에러 프레임 매핑, 하트비트 pong
  - basic example

v0.2.0
  - 종단 payload 확장(transcript / summary / usage) 수신 (gateway 제공 시)
  - agent runtime extra (tello-sdk[agent])

v0.3.0
  - 자동 재연결 (gateway resume 지원 시)

v1.0.0
  - WS 프로토콜 1.0 고정
  - contract test 고정
  - Python / Node / Java / Go 기본 기능 parity
```

초기 공식 SDK는 Python, Node.js, Java, Go까지 지원한다. PHP, Ruby, C#은 실제 고객 요청 전까지 만들지 않는다.

---

## 15. 결정 사항 요약

- SDK 루트는 `sdk/`로 분리한다.
- **SDK 전송은 WebSocket 전용이다. REST/webhook은 범위 밖.**
- 계약은 `sdk/contracts/`(WS 프로토콜 문서 + 이벤트/에러 JSON Schema)를 기준으로 한다.
- SDK는 서버 내부 구현을 import하지 않는다. 외부 계약은 WS 명령/이벤트 프레임뿐이다.
- 프로토콜 major version은 프레임 `version` 필드로 관리한다.
- SDK는 SemVer를 따른다.
- Python / Node / Java / Go SDK는 기능 parity를 목표로 한다.
- SDK minor / major 버전은 lockstep으로 같이 올린다.
- SDK patch 버전은 언어별 버그 수정에 한해 따로 올릴 수 있다.
- 배포는 모노레포에서 시작하되 PyPI / npm / Maven Central / Go tag로 각각 나간다.
- Go SDK는 고객 import path를 위해 별도 `tello-sdk-go` mirror repo 운영을 권장한다.
- breaking change는 SDK major 또는 프로토콜 `2.0`으로만 처리한다.
- 초기 릴리스(v0.1)는 WS realtime 핵심(create_call/answer/cancel + turn 이벤트)부터 시작한다.
