# Tello Voice — Agent 연계형 개발자 온보딩 가이드

> 버전: v1.0 | 작성일: 2026-06-29
> 대상: Phase 2 Agent 연계형 기능을 개발·통합하는 신규 개발자
> 연관 문서: `Tello_Agent연계형_SDK_방향성_v1_0.md` / `Tello_Voice_프로그램설계서_v1_0.md` / `masterplan v2.35`

---

## 목차

1. [배경 — Phase 1 위임형 vs Phase 2 Agent 연계형](#1-배경)
2. [전체 아키텍처 개요](#2-전체-아키텍처-개요)
3. [핵심 포지셔닝](#3-핵심-포지셔닝)
4. [방식 A — MCP 도구형 (telephony_listen / telephony_speak)](#4-방식-a--mcp-도구형)
5. [방식 B — SDK형 (Python / Node.js)](#5-방식-b--sdk형)
6. [두 방식 비교 및 선택 기준](#6-두-방식-비교-및-선택-기준)
7. [레이턴시 고려사항 및 대응 전략](#7-레이턴시-고려사항)
8. [VGW 내부 구조 — 개발자 필수 이해](#8-vgw-내부-구조)
9. [신규 MCP 도구 구현 명세 (telephony_listen / telephony_speak)](#9-신규-mcp-도구-구현-명세)
10. [SDK 구현 명세](#10-sdk-구현-명세)
11. [로컬 개발 환경 설정](#11-로컬-개발-환경-설정)
12. [구현 우선순위 및 담당 분배](#12-구현-우선순위-및-담당-분배)
13. [FAQ / 트러블슈팅](#13-faq--트러블슈팅)

---

## 1. 배경

### 1.1 Phase 1 — 위임형 (현재 운영 중)

현재 Tello가 제공하는 구조는 **위임형**이다.
AI 에이전트(Claude, GPT 등)는 전화를 시작하고 결과를 받는 역할만 하며,
통화 중 대화는 Tello 내부 LLM(gemini-2.5-flash-lite)이 처리한다.

```
Claude (AI 에이전트)
    │
    ▼ telephony_call(to, prompt)    ← 전화 연결 + 목적 전달
Tello MCP Server
    │
    ▼
Tello VGW (Pipecat)
    │  STT → 내부 LLM → TTS       ← 통화 중 대화 Tello가 처리
    │
    ▼
상대방
    │
    ▼ telephony_get_summary()       ← 통화 종료 후 결과 수신
Claude
```

**위임형의 한계:**
- Claude는 통화 중 개입 불가
- 가입자 내부 시스템(CRM, ERP, DB)과 실시간 연동 불가
- 통화 흐름 제어를 Tello LLM에 의존

---

### 1.2 Phase 2 — Agent 연계형 (목표)

**Agent 연계형**에서는 Tello가 귀(STT)와 입(TTS)만 제공하고,
**두뇌(대화 판단)는 가입자의 AI 에이전트가 담당**한다.

```
Claude (AI 에이전트)
    │
    ▼ telephony_call(to, prompt)    ← 전화 연결 요청
Tello VGW
    │
    ▼ 전화 연결됨
상대방 발화 → STT
    │
    ▼ 텍스트 전달 (실시간)
Claude가 직접 판단 + 응답 생성
    │
    ▼ 응답 전달
Tello VGW → TTS → 음성 출력
    │
    ▼ (반복)
통화 종료
```

이 구조를 실현하는 방법은 두 가지다.

| 방법 | 대상 | 키워드 |
|------|------|--------|
| **방식 A — MCP 도구형** | Claude.ai / 비개발자 포함 | telephony_listen, telephony_speak |
| **방식 B — SDK형** | 개발자 / 기업 자체 AI 보유 | Python / Node.js SDK |

---

## 2. 전체 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│                        Tello 플랫폼                          │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  mcp-server  │    │  intent-flow │    │     VGW      │  │
│  │  (Node.js)   │◄──►│  (Node.js)   │    │  (Python     │  │
│  │              │    │              │    │   Pipecat)   │  │
│  │ /api/mcp     │    │ /analyze     │    │              │  │
│  │ telephony_*  │    │ /outcome     │    │ STT/LLM/TTS  │  │
│  └──────┬───────┘    └──────────────┘    └──────┬───────┘  │
│         │                                        │          │
│         └──────────────────────────────────────► │          │
│                                                  │ SIP/WebRTC│
└──────────────────────────────────────────────────┼──────────┘
                                                   │
                                              상대방 전화
```

**6개 Railway 서비스:**

| 서비스 | 언어 | 역할 |
|--------|------|------|
| `portal` | Next.js 14 | 가입자 포털 UI + BFF API |
| `mcp-server` | Node.js | MCP 도구 노출 + 통화 오케스트레이션 |
| `intent-flow` | Node.js | Goal 검증 + 통화 결과 판정 |
| `vgw` | Python / Pipecat 1.4.0 | 음성 파이프라인 (STT→LLM→TTS) |
| `crawl-service` | Python / Playwright | URL 크롤링 → Knowledge 저장 |
| `OpenBao` | Go | 시크릿 관리 (Transit 암복호화 + KV) |

---

## 3. 핵심 포지셔닝

```
Tello = 전화 인프라 + STT + TTS 제공
두뇌  = 가입자 AI 에이전트 (Claude, GPT, 자체 LLM 등)
```

> **"전화는 우리가, 판단은 당신의 AI가"**

Agent 연계형에서 VGW는 다음만 한다.

- 음성 수신 → Deepgram STT → 텍스트 추출
- 가입자 AI로부터 응답 텍스트 수신
- Cartesia TTS → 음성 출력

**VGW 내부 LLM은 Agent 연계형 통화에서 비활성화된다.**

---

## 4. 방식 A — MCP 도구형

### 4.1 개요

별도 서버 없이 **MCP 도구 호출만으로** 통화 중 대화를 Claude가 직접 제어하는 방식.
Claude.ai에서 즉시 사용 가능하며, 도입 허들이 가장 낮다.

### 4.2 신규 MCP 도구

Phase 2-A에서 추가되는 도구 2종:

| 도구 | 역할 |
|------|------|
| `telephony_listen` | 상대방 최신 발화 텍스트 폴링 |
| `telephony_speak` | 응답 텍스트를 VGW에 전달 (TTS 실행) |

### 4.3 Claude 동작 흐름 예시

```python
# Claude가 MCP 도구만으로 전화를 제어하는 흐름 (의사 코드)

# 1. 전화 연결
result = telephony_call(
    to="010-1234-5678",
    agent_id=42,
    prompt="배달 주문 상태 안내"
)
call_id = result["call_id"]

# 2. 통화 중 루프
while True:
    # 상대방 발화 폴링
    listen_result = telephony_listen(call_id=call_id)
    
    if listen_result["status"] == "ended":
        break
    
    if listen_result["status"] == "speaking":
        utterance = listen_result["text"]
        
        # Claude가 직접 판단 + 응답 생성
        # (이 판단 과정에서 다른 MCP 도구도 활용 가능)
        # 예: calendar_search(), db_query(), send_email() 등
        
        response_text = "..."  # Claude의 응답
        
        # 응답을 VGW로 전달 (TTS 실행)
        telephony_speak(
            call_id=call_id,
            text=response_text
        )

# 3. 통화 요약 수신
summary = telephony_get_summary(call_id=call_id)
```

### 4.4 telephony_listen 응답 스펙

```json
{
  "call_id": "uuid",
  "status": "speaking | waiting | ended",
  "text": "고객 발화 텍스트 (status=speaking일 때만)",
  "utterance_id": "uuid",
  "timestamp": "ISO8601"
}
```

**status 값 설명:**

| status | 의미 | Claude 행동 |
|--------|------|-------------|
| `waiting` | 상대방이 아직 말하지 않음 | 재폴링 (짧은 대기) |
| `speaking` | 새 발화 있음 | text 읽고 응답 생성 |
| `ended` | 통화 종료 | 루프 탈출 |

### 4.5 telephony_speak 요청 스펙

```json
{
  "call_id": "uuid",
  "text": "Claude가 생성한 응답 텍스트",
  "utterance_id": "optional — 대응하는 listen utterance_id (중복 방지)"
}
```

### 4.6 MCP 도구형의 특징

**장점:**

- 가입자 준비 사항: **없음** (MCP 연결만 있으면 됨)
- Claude.ai 대화창에서 바로 전화 제어 가능
- 통화 중 다른 MCP 도구 자유롭게 활용 가능
  (캘린더 조회, DB 검색, 이메일 발송, Slack 알림 등)
- 비개발자도 사용 가능

**제약:**

- Claude 판단 시간(수초)만큼 응답 지연 발생
- FillerProcessor가 대기 시간 커버 (기본 3초)
- Claude.ai 외부 내부망 시스템 연동 제한

---

## 5. 방식 B — SDK형

### 5.1 개요

> **SDK 전송은 WebSocket 전용이다.** 가입자 앱이 turn-provider-gateway의 `/sdk` WebSocket에 **outbound 연결**을 열고, 그 위에서 통화를 시작하고 상대방 발화(turn)를 이벤트로 받아 응답한다. 콜백 HTTP 서버를 띄우거나 웹훅(HMAC)을 검증하는 방식은 쓰지 않는다. 프로토콜 계약은 `docs/protocol/sdk-ws.v1.md`가 기준이다.

가입자 앱은 SDK로 gateway에 WS 연결을 열고, 발화 이벤트를 pub/sub 핸들러로 받아 가입자 AI 응답을 되돌린다.

```
가입자 앱 (SDK)
    │  WS connect  ws(s)://<host>/sdk  (Authorization: Bearer <api_key>)
    ▼
turn-provider-gateway  ◄──►  VGW
    │
    ▼ user.turn 이벤트 (상대방 STT 텍스트, WS 프레임)
가입자 앱 SDK 핸들러
    │
    ▼ 가입자 AI 로직 실행 (사내 LLM, ERP 조회 등)
    │
    ▼ answer(text) 전송 (WS 프레임)
turn-provider-gateway → VGW
    │
    ▼ TTS → 음성 출력
```

### 5.2 Python SDK 사용법

#### 설치

```bash
pip install tello-sdk
```

#### 기본 사용 예시

```python
import asyncio
from tello import TelloClient, EventType

async def main():
    # gateway /sdk WebSocket에 연결 (연결 시 Bearer 인증)
    async with TelloClient(
        api_key="tello_live_xxxxxxxxxxxx",
        url="ws://localhost:3000/sdk",
    ) as client:

        # 상대방 발화 수신 → 응답 전송 (pub/sub)
        @client.on(EventType.USER_TURN)
        async def on_user_turn(event):
            # event.text: 상대방 STT 텍스트
            response = await my_ai.respond(event.text)
            await client.answer(text=response)

        # 통화 종료 (선택)
        @client.on(EventType.CALL_COMPLETED)
        async def on_completed(event):
            print(f"통화 종료: {event.call_id}")

        # 통화 시작
        await client.create_call(to="+821012345678", agent_id="agent-1", prompt="예약 확인")
        await client.wait_closed()   # 종단 이벤트까지 대기

asyncio.run(main())
```

#### 포털에서 API key 발급

```
에이전트 설정 → 고급 → Agent 연계형 (SDK)
└─ API Key: [발급/재발급]  (WS 연결 시 Authorization: Bearer 로 사용)
```

### 5.3 Node.js SDK 사용법

#### 설치

```bash
npm install @tello/sdk
```

#### 기본 사용 예시

```typescript
import { TelloClient } from '@tello/sdk';

const client = new TelloClient({
  apiKey: 'tello_live_xxxxxxxxxxxx',
  url: 'ws://localhost:3000/sdk',
});

await client.connect();

// 상대방 발화 수신 → 응답 전송 (pub/sub)
client.on('user.turn', async (event) => {
  const response = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'user', content: event.text }],
  });
  await client.answer({ text: response.choices[0].message.content });
});

client.on('call.completed', (event) => {
  console.log('통화 종료', event.callId);
});

await client.createCall('+821012345678', 'agent-1', '예약 확인');
await client.waitClosed();
```

### 5.4 WS 이벤트 프레임 스펙

gateway → SDK로 오는 인바운드 프레임은 봉투 없이 flat이며 `type`으로 구분한다(전체 목록은 `docs/protocol/sdk-ws.v1.md`). 상대방 발화:

```json
{
  "type": "user.turn",
  "version": "1.0",
  "sessionId": "uuid",
  "callId": "uuid",
  "turnIndex": 1,
  "text": "STT 결과 텍스트",
  "timestamp": "2026-06-29T10:00:00Z"
}
```

SDK → gateway 응답은 `answer` 명령 프레임(봉투 있음):

```json
{ "event": "answer", "data": { "text": "가입자 AI가 생성한 응답 텍스트" } }
```

통화를 끝내려면 `cancel` 명령을 보낸다. 통화 종단은 `call.completed` / `call.noAnswer` / `call.failed` 이벤트로 통지된다.

### 5.5 연결 인증

WS 연결 시 `Authorization: Bearer <api_key>` 헤더(또는 `?token=` 쿼리)로 인증한다. 별도의 콜백 HMAC 서명 검증은 필요 없다(가입자가 서버를 노출하지 않고 outbound 연결만 열기 때문). 인증 실패 시 gateway가 close code `4401`로 연결을 끊는다.

### 5.6 SDK형의 특징

**장점:**
- 사내 ERP, CRM, RAG 시스템과 직접 연동
- 응답 로직 완전 제어 (if/else, 룰 기반, 시나리오 스크립트)
- Claude에 비종속적 — 자체 LLM 사용 가능
- inbound 포트 개방 불필요 — outbound WS만 열면 되어 내부망(금융, 공공, 의료)에서도 유리
- MCP 방식 대비 응답 레이턴시 단축 가능

**제약:**
- 클라이언트 앱 운영 필요 (가입자 책임)
- 개발자 필요
- WS 연결 유지/재연결 관리 필요 (현재 gateway는 세션 resume 미지원)

---

## 6. 두 방식 비교 및 선택 기준

| 항목 | 방식 A (MCP 도구형) | 방식 B (SDK형) |
|------|---------------------|----------------|
| 가입자 준비 | **없음** | SDK 설치 + 서버 운영 |
| 개발자 필요 | **불필요** | 필요 |
| 두뇌 위치 | Claude.ai | 가입자 서버 |
| 기존 시스템 통합 | 제한적 | **용이 (ERP/CRM/RAG)** |
| 내부망 처리 | 불가 | **가능** |
| 응답 레이턴시 | 수초 (Claude 판단) | ~수백ms (자체 서버) |
| 도입 허들 | **최저** | 낮음 |
| Claude 종속성 | 있음 | **없음** |
| 통화 중 MCP 도구 사용 | **자유롭게 가능** | 직접 구현 필요 |
| 대상 고객 | AI 에이전트 사용자, 비개발자 | 개발자, 기업 |

**선택 가이드:**

```
Q1. 내부 시스템(ERP/CRM) 실시간 연동이 필요한가?
    YES → SDK형 (방식 B)

Q2. 자체 LLM을 보유하고 있거나 Claude 외 AI를 쓰고 싶은가?
    YES → SDK형 (방식 B)

Q3. 개발 인력이 없거나 빠른 PoC가 목적인가?
    YES → MCP 도구형 (방식 A)

Q4. 통화 중 Claude의 다른 도구(캘린더, DB 등)도 함께 쓰고 싶은가?
    YES → MCP 도구형 (방식 A)
```

---

## 7. 레이턴시 고려사항

### 7.1 MCP 도구형 레이턴시 구조

```
상대방 발화 종료
    │ ~100ms
    ▼ STT 완료 → telephony_listen 응답
    │
    ▼ Claude LLM 추론 (수초 — 가장 긴 구간)
    │
    ▼ telephony_speak 호출
    │ ~40ms (Cartesia TTS)
    ▼ 음성 출력

총 체감 응답 시간: 약 2~5초
```

### 7.2 SDK형 레이턴시 구조

```
상대방 발화 종료
    │ ~100ms
    ▼ STT 완료 → user.turn WS 프레임 push
    │ 가입자 앱 처리 + answer WS 프레임 왕복 (수십~수백ms)
    ▼ 응답 텍스트 수신
    │ ~40ms (Cartesia TTS)
    ▼ 음성 출력

총 체감 응답 시간: 약 300~800ms (자체 처리 최적화 시)
```

### 7.3 FillerProcessor (레이턴시 완화)

응답 지연이 발생하는 동안 사용자 경험 보호를 위해 필러 발화를 삽입한다.

```python
# vgw/processors/filler.py
# 설정 기준 (에이전트별 조정 가능)
FILLER_TIMEOUT_MS = 3000   # 응답 대기 3초 후 필러 발화

DEFAULT_FILLERS = [
    "네, 잠시만요.",
    "확인해볼게요.",
    "잠깐만요.",
    "네~"
]
```

**Agent 연계형 에이전트 권장 설정:**

```
에이전트 설정 → 고급 → Filler
└─ Filler 간격: 1000~1500ms (기본 3000ms보다 짧게)
└─ Filler 텍스트: 통화 맥락에 맞게 커스터마이즈
```

---

## 8. VGW 내부 구조

Agent 연계형 개발 시 반드시 이해해야 하는 VGW 파이프라인.

### 8.1 현재 파이프라인 (Phase 1 위임형)

```
[SIP/WebRTC 입력]
    ↓
[Silero VAD]                   ← 음성 활성 감지
    ↓
[Deepgram STT (Nova-3)]        ← 음성 → 텍스트
    ↓
[FillerProcessor]              ← 응답 대기 중 간투어
    ↓
[DynamicEndpointingProcessor]  ← 발화 종료 감지 최적화
    ↓
[KnowledgeContextProcessor]    ← RAG 검색 (Knowledge 활성화 시)
    ↓
[LLM (gemini-2.5-flash-lite)]  ← 내부 AI 판단 ← Agent 연계형에서 이 부분이 대체됨
    ↓
[EmotionProcessor]             ← <E:태그> 변환
    ↓
[TTS Adapter (Cartesia)]       ← 텍스트 → 음성
    ↓
[SIP/WebRTC 출력]
```

### 8.2 Agent 연계형 파이프라인 변경

```
[SIP/WebRTC 입력]
    ↓
[Silero VAD]
    ↓
[Deepgram STT (Nova-3)]
    ↓
[FillerProcessor]
    ↓
[DynamicEndpointingProcessor]
    ↓
    ├─ 위임형: [LLM (내부)] → [EmotionProcessor] → [TTS]
    │
    └─ Agent 연계형:
         ├─ MCP형: telephony_listen 폴링 응답 → [TTS]
         └─ SDK형: turn-provider-gateway WS(user.turn↔answer) → [TTS]
```

**Agent 연계형 활성화 조건:**
에이전트 설정에서 `agent_type = "agent_linked"` 설정 시 VGW가 자동 분기.

### 8.3 주요 파일 위치

```
vgw/
├── pipeline/
│   ├── livekit_bot.py        ← 봇 메인, 파이프라인 구성, 분기 로직
│   └── session.py            ← AgentConfig, CallSession
├── processors/
│   ├── filler.py             ← FillerProcessor
│   ├── dynamic_endpointing.py
│   ├── emotion.py            ← EmotionProcessor
│   └── knowledge_context.py  ← RAG
├── tts/
│   └── adapter.py            ← TTSAdapter (Cartesia / ElevenLabs)
├── services/
│   ├── recording.py          ← 통화 녹취 (PCM → mp3 → AES → Storage)
│   ├── callback.py           ← 통화 완료 콜백 → portal / intent-flow
│   └── agent_linked.py       ← [신규] Agent 연계형 처리 (MCP폴링/SDK콜백)
└── routers/
    └── calls.py              ← /internal/calls, /internal/create-room
```

---

## 9. 신규 MCP 도구 구현 명세

### 9.1 telephony_listen

**파일:** `mcp-server/src/tools/telephony-listen.ts`

```typescript
import { z } from 'zod';
import { Tool } from '@modelcontextprotocol/sdk/types.js';
import { supabase } from '../lib/supabase.js';

export const telephonyListenTool: Tool = {
  name: 'telephony_listen',
  description: '통화 중 상대방의 최신 발화 텍스트를 가져옵니다. Agent 연계형 통화에서만 사용 가능합니다.',
  inputSchema: {
    type: 'object',
    properties: {
      call_id: {
        type: 'string',
        description: 'telephony_call로 획득한 call_id'
      },
      utterance_id: {
        type: 'string',
        description: '마지막으로 수신한 utterance_id (중복 수신 방지)'
      }
    },
    required: ['call_id']
  }
};

export async function handleTelephonyListen(args: {
  call_id: string;
  utterance_id?: string;
}, accountId: number) {
  // 1. 통화 상태 확인
  const { data: call } = await supabase
    .from('tb_mcp_call_records')
    .select('call_status, agent_type')
    .eq('call_id', args.call_id)
    .eq('account_id', accountId)
    .single();

  if (!call) {
    return { status: 'error', message: '유효하지 않은 call_id' };
  }
  if (call.call_status === 'ended' || call.call_status === 'failed') {
    return { status: 'ended' };
  }
  if (call.agent_type !== 'agent_linked') {
    return { status: 'error', message: 'Agent 연계형 에이전트에서만 사용 가능합니다.' };
  }

  // 2. VGW에서 최신 발화 조회 (polling)
  const { data: utterance } = await supabase
    .from('tb_mcp_call_utterances')  // 신규 테이블
    .select('*')
    .eq('call_id', args.call_id)
    .eq('role', 'user')
    .neq('utterance_id', args.utterance_id ?? '')
    .order('created_at', { ascending: false })
    .limit(1)
    .single();

  if (!utterance) {
    return { status: 'waiting', call_id: args.call_id };
  }

  return {
    status: 'speaking',
    call_id: args.call_id,
    text: utterance.text,
    utterance_id: utterance.utterance_id,
    timestamp: utterance.created_at
  };
}
```

### 9.2 telephony_speak

**파일:** `mcp-server/src/tools/telephony-speak.ts`

```typescript
export const telephonySpeakTool: Tool = {
  name: 'telephony_speak',
  description: 'Agent 연계형 통화에서 응답 텍스트를 VGW로 전달합니다. VGW는 이 텍스트를 TTS로 변환하여 상대방에게 발화합니다.',
  inputSchema: {
    type: 'object',
    properties: {
      call_id: { type: 'string', description: 'call_id' },
      text: { type: 'string', description: '발화할 텍스트 (최대 500자)' },
      utterance_id: { type: 'string', description: '대응하는 listen utterance_id (중복 방지)' },
      end_call: { type: 'boolean', description: 'true 시 발화 후 통화 종료' }
    },
    required: ['call_id', 'text']
  }
};

export async function handleTelephonySpeak(args: {
  call_id: string;
  text: string;
  utterance_id?: string;
  end_call?: boolean;
}, accountId: number) {
  // 1. VGW에 응답 전달
  const vgwUrl = process.env.VGW_URL;
  const res = await fetch(`${vgwUrl}/internal/agent-speak`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Key': process.env.INTERNAL_SERVICE_KEY!
    },
    body: JSON.stringify({
      call_id: args.call_id,
      text: args.text,
      utterance_id: args.utterance_id,
      end_call: args.end_call ?? false
    })
  });

  if (!res.ok) {
    return { success: false, error: '응답 전달 실패' };
  }

  // 2. DB에 어시스턴트 발화 기록
  await supabase
    .from('tb_mcp_call_utterances')
    .insert({
      call_id: args.call_id,
      role: 'assistant',
      text: args.text,
      source: 'mcp'
    });

  return {
    success: true,
    call_id: args.call_id,
    text: args.text
  };
}
```

### 9.3 신규 DB 테이블 — tb_mcp_call_utterances

```sql
-- Agent 연계형 발화 버퍼 테이블
CREATE TABLE tb_mcp_call_utterances (
    utterance_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id        UUID NOT NULL REFERENCES tb_mcp_call_records(call_id) ON DELETE CASCADE,
    role           VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    text           TEXT NOT NULL,
    source         VARCHAR(20) DEFAULT 'vgw' CHECK (source IN ('vgw', 'mcp', 'sdk')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_utterances_call_id ON tb_mcp_call_utterances(call_id);
CREATE INDEX idx_utterances_created ON tb_mcp_call_utterances(call_id, created_at DESC);
```

### 9.4 VGW 신규 엔드포인트 — /internal/agent-speak

**파일:** `vgw/routers/calls.py` (추가)

```python
@router.post("/internal/agent-speak")
async def agent_speak(request: Request, data: dict = Body(...)):
    """
    MCP Server → VGW: Agent 연계형 응답 텍스트 수신 → TTS 실행
    """
    verify_internal_key(request)

    call_id = data["call_id"]
    text = data["text"]
    end_call = data.get("end_call", False)

    session = active_sessions.get(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="통화 세션 없음")

    # TTS 파이프라인에 텍스트 주입
    await session.inject_response(text, end_call=end_call)

    return {"success": True}
```

---

## 10. SDK 구현 명세

### 10.1 패키지 구조

전송이 WebSocket이므로 콜백 수신 서버(FastAPI)나 HMAC 모듈은 두지 않는다. 언어별 상세 구조는 `sdk/sdk-directory.md` §2를 따른다(Python 예: `tello-python`).

```
tello-python/
└── src/tello/
    ├── __init__.py
    ├── client.py       ← TelloClient (WS 연결 수명주기 + 명령 전송 + 인바운드 디스패치)
    ├── realtime.py     ← pub/sub 이벤트 핸들러 + answer
    ├── events.py       ← 인바운드 flat 프레임 파서 + EventType
    ├── commands.py     ← 아웃바운드 {event,data} 봉투 빌더
    ├── errors.py       ← 에러 code → 예외 매핑
    ├── types.py        ← PublicStatus 등
    └── config.py
```

### 10.2 SDK → gateway WS 플로우

```
고객 발화 종료
    │
    ▼ [Deepgram STT 완료]
VGW → turn-provider-gateway
    │
    ▼ user.turn WS 프레임 push (봉투 없는 flat)
    │   { type:"user.turn", sessionId, callId, turnIndex, text, ... }
    │
가입자 앱 (SDK, outbound WS 연결)
    │ 이벤트 pub/sub 디스패치
    │ user.turn 핸들러 실행
    │
    ▼ answer 명령 프레임 전송: { event:"answer", data:{ text } }
turn-provider-gateway → VGW
    │
    ▼ TTS → 음성 출력
```

### 10.3 포털 에이전트 설정 — SDK 연동 항목

```
에이전트 설정 → 고급 → Agent 연계형
┌────────────────────────────────────────────────┐
│ 연계 방식    ○ 위임형 (기본)                    │
│             ○ MCP 도구형 (telephony_listen)     │
│             ● SDK (WebSocket)                   │
│                                                 │
│ API Key     tello_live_••••••  [발급] [재발급]  │
│             (WS 연결 시 Authorization: Bearer)  │
└────────────────────────────────────────────────┘
```

SDK는 발급된 API Key로 gateway `/sdk`에 outbound WS 연결을 연다. 포털에 콜백 URL을 등록할 필요가 없다.

---

## 11. 로컬 개발 환경 설정

### 11.1 전제 조건

```bash
# 버전 확인
node --version    # 20.x 이상
python --version  # 3.11 이상
git --version

# ffmpeg (vgw 녹취용, macOS)
brew install ffmpeg

# ffmpeg (Ubuntu/Debian)
apt-get install ffmpeg
```

### 11.2 레포 클론 및 설치

```bash
git clone https://github.com/YoungjoonKoo/ipron-mcp.git
cd ipron-mcp

# portal
cd portal && npm install && cd ..

# mcp-server
cd mcp-server && npm install && cd ..

# intent-flow
cd intent-flow && npm install && cd ..

# vgw
cd vgw
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

### 11.3 환경변수 설정

각 서비스 디렉토리에 `.env` 파일 생성.
Railway 프로젝트 환경변수에서 복사하거나 팀원에게 요청.

**mcp-server/.env (핵심)**

```env
SUPABASE_URL=https://iifybxbmcnzcgjqocqjy.supabase.co
SUPABASE_SERVICE_KEY=<service_key>
INTENT_FLOW_URL=http://localhost:3002
VGW_URL=http://localhost:8080
INTERNAL_SERVICE_KEY=secret123
OPENROUTER_API_KEY=<key>
# OpenBao 미설정 시 로컬 AES 동작 (개발 가능)
```

**vgw/.env (핵심)**

```env
LIVEKIT_URL=wss://ipron-mcp-rhz7osbj.livekit.cloud
LIVEKIT_API_KEY=<key>
LIVEKIT_API_SECRET=<secret>
DEEPGRAM_API_KEY=<key>
TTS_PROVIDER=cartesia
TTS_MODEL=sonic-3-latest
CARTESIA_API_KEY=<key>
CARTESIA_VOICE_ID=<voice_id>
OPENROUTER_API_KEY=<key>
SUPABASE_URL=https://iifybxbmcnzcgjqocqjy.supabase.co
SUPABASE_SERVICE_KEY=<key>
INTERNAL_SERVICE_KEY=secret123
PORTAL_CALLBACK_URL=http://localhost:3000
INTENT_FLOW_URL=http://localhost:3002
RECORDING_ENABLED=false         # 로컬 개발 시 false 권장
```

### 11.4 서비스 실행

```bash
# 터미널 1 — portal
cd portal && npm run dev

# 터미널 2 — mcp-server
cd mcp-server && npm run dev

# 터미널 3 — intent-flow
cd intent-flow && npm run dev

# 터미널 4 — vgw
cd vgw && source .venv/bin/activate
uvicorn main:app --reload --port 8080
```

### 11.5 테스트 계정

```
이메일: test@ipron.kr
비밀번호: test1234
account_id: 1
```

### 11.6 SIP 없이 테스트하기

실제 SIP 통화 없이 VGW 파이프라인을 테스트하려면:
1. 포털 → 에이전트 상세 → `[테스트]` 버튼 사용 (WebRTC)
2. 또는 MicroSIP + LiveKit SIP 인바운드 (SIP 설정 필요)

SIP 실통화 테스트는 LiveKit Cloud 연동 필수.

---

## 12. 구현 우선순위 및 담당 분배

### Phase 2-A (MCP 도구형 먼저 — 4~6주 예상)

| 순위 | 작업 | 서비스 | 담당 | 예상 공수 |
|------|------|--------|------|-----------|
| 1 | `tb_mcp_call_utterances` 테이블 생성 | DB | - | 0.5일 |
| 2 | `telephony_listen` 도구 구현 | mcp-server | 개발자 B | 2일 |
| 3 | `telephony_speak` 도구 구현 | mcp-server | 개발자 B | 1일 |
| 4 | VGW `/internal/agent-speak` 엔드포인트 | vgw | 개발자 C | 2일 |
| 5 | VGW Agent 연계형 세션 분기 | vgw | 개발자 C | 3일 |
| 6 | VGW STT 결과 → utterances 저장 | vgw | 개발자 C | 1일 |
| 7 | 포털 에이전트 설정 — 연계형 토글 | portal | 개발자 A | 2일 |
| 8 | 통합 테스트 (Claude.ai + 실통화) | 공통 | - | 3일 |

### Phase 2-B (SDK형 — 추가 6~8주)

| 순위 | 작업 | 예상 공수 |
|------|------|-----------|
| 1 | SDK 패키지 구조 설계 (WS 계약 확정) | 1일 |
| 2 | Python SDK 구현 (asyncio + websockets, pub/sub) | 5일 |
| 3 | Node.js SDK 구현 | 4일 |
| 4 | turn-provider-gateway `/sdk` WS 엔드포인트 | (구현 완료) |
| 5 | 포털 API Key 발급/관리 UI | 2일 |
| 6 | gateway ↔ VGW turn 브리지 연동 검증 | 3일 |
| 7 | SDK 문서 + 예제 코드 | 3일 |
| 8 | PyPI / npm 배포 | 1일 |

---

## 13. FAQ / 트러블슈팅

### Q1. telephony_listen이 계속 `waiting`을 반환한다

VGW가 STT 완료 후 utterances 테이블에 기록하지 못하는 상황일 수 있다.

**확인 순서:**
1. VGW 로그에서 STT 완료 이벤트 확인
2. `tb_mcp_call_utterances` 테이블에 레코드가 쌓이는지 확인
3. call_id / account_id 불일치 여부 확인

### Q2. telephony_speak를 호출했는데 음성이 나오지 않는다

**확인 순서:**
1. VGW `/internal/agent-speak` 응답 코드 확인 (404 = 세션 없음)
2. `active_sessions` 딕셔너리에 call_id가 존재하는지 확인
3. INTERNAL_SERVICE_KEY 일치 여부 확인 (mcp-server ↔ vgw)

### Q3. SDK에서 answer를 보냈는데 음성이 안 나온다

**확인 순서:**
1. `answer` 명령 프레임 형식 확인: `{ "event": "answer", "data": { "text": "..." } }` (봉투 필수)
2. 활성 통화 여부 확인 — `noActiveCall` 에러 프레임이 오는지 (create_call 성공 후에만 answer 가능)
3. WS 연결 유지 여부 — heartbeat ping에 pong 응답이 되는지 (표준 WS 라이브러리는 자동)

### Q4. FillerProcessor가 동작하지 않는다

에이전트 설정의 `filler_timeout_ms`와 VGW 환경변수 `FILLER_TIMEOUT_MS`를 확인.
`FILLER_ENABLED=true` 설정 필수.

### Q5. Agent 연계형에서도 Knowledge RAG가 동작하는가

현재 설계에서는 **Agent 연계형 시 RAG는 비활성화**된다.
가입자 AI가 자체 컨텍스트를 관리하는 것이 원칙이기 때문.
단, SDK형에서 가입자가 자체 RAG를 콜백 핸들러 내부에서 호출하는 것은 가능하다.

### Q6. 인바운드 통화도 Agent 연계형 지원 예정인가

Phase 2에서 지원 예정. 현재(Phase 1)는 인바운드가 Intent Flow를 거치지 않으며,
Agent 연계형도 우선 아웃바운드(telephony_call) 기준으로 구현한다.

### Q7. 개발 중 OpenBao 없이도 동작하는가

`.env`에 `OPENBAO_URL`을 설정하지 않으면 자동으로 로컬 AES(EnvSecrets) 모드로 동작.
BYOK 기능을 테스트하지 않는 개발 환경에서는 OpenBao 없이 가능하다.

---

## 부록 A. 관련 문서 목록

| 문서 | 경로 | 내용 |
|------|------|------|
| 마스터플랜 | `docs/IPRON_Cloud_Telephony_MCP_masterplan_v2_35.md` | 전체 제품 전략 |
| 포털기술명세 | `docs/IPRON_Cloud_Telephony_MCP_포털기술명세_v3_10.md` | API 상세 명세 |
| DB설계 | `docs/IPRON_Cloud_Telephony_MCP_DB설계_v3_0.md` | 테이블 전체 목록 |
| SDK 방향성 | `docs/Tello_Agent연계형_SDK_방향성_v1_0.md` | 아키텍처 논의 원본 |
| 프로그램설계서 | `docs/Tello_Voice_프로그램설계서_v1_0.md` | 서비스별 설계 |
| DB 레이아웃 | `docs/Tello_Voice_DB_Layout_v1_1.md` | 테이블 레이아웃 요약 |

## 부록 B. 브랜치 전략

```
main          ← 운영 배포 (Railway 자동 빌드)
dev           ← 통합 테스트
feat/listen-speak   ← Phase 2-A MCP 도구 구현
feat/sdk-python     ← Python SDK
feat/sdk-nodejs     ← Node.js SDK
```

PR 기준: `feat/* → dev` (코드리뷰 필수) → `dev → main` (Kevin 승인)

## 부록 C. Railway Watch Paths

서비스별 디렉토리 변경 시에만 빌드가 트리거된다. 모노레포 구조를 반드시 준수.

```
portal/**         → portal 서비스만 빌드
mcp-server/**     → mcp-server 서비스만 빌드
vgw/**            → vgw 서비스만 빌드
intent-flow/**    → intent-flow 서비스만 빌드
crawl-service/**  → crawl-service 서비스만 빌드
```

루트 파일(CLAUDE.md, README.md 등) 수정은 어느 서비스도 빌드하지 않음.

---

*작성일: 2026-06-29 | Tello Voice 개발팀*
*다음 업데이트: Phase 2-A 구현 착수 시 API 스펙 확정 반영*
