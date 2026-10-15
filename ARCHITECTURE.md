# Architecture: Audio-First Socratic Language Learning Web App

## 1. Overview

The system is a dual-process tutor:

1. **System 2 — E2E Full-Duplex Speech Engine**: handles listening, language understanding, dialogue generation, and natural speech output. It is creative, high-latency, and stateful.
2. **System 1 — TypeSafe / Jev Governor**: a deterministic guardrail that validates every tutor turn against lesson state, drift, and Socratic compliance. It is fast (<150 ms), typed, and content-agnostic.

The frontend streams raw PCM audio from the microphone and receives both audio buffers and out-of-band control messages over a single WebSocket.

---

## 2. Component Diagram

```textn
┌─────────────────────────────┐
│         Browser             │
│  ┌───────────────────────┐  │
│  │  useAudioRecorder()   │  │  ← Web Audio API → raw PCM
│  └──────────┬────────────┘  │
│             │               │
│  ┌──────────▼────────────┐  │
│  │   useDuplexSocket()   │  │  ← WebSocket to /ws/audio-tutor
│  └──────────┬────────────┘  │
│             │               │
│  ┌──────────▼────────────┐  │
│  │     LessonRoom        │  │
│  │  VisualAssistOverlay  │  │  ← pull-based hints, hidden by default
│  └───────────────────────┘  │
└─────────────┬───────────────┘
              │ WebSocket (audio + control frames)
┌─────────────▼───────────────┐
│      FastAPI Backend        │
│  ┌───────────────────────┐  │
│  │   /ws/audio-tutor     │  │
│  │  binary audio frames  │  │
│  │  JSON control frames  │  │
│  └──────────┬────────────┘  │
│             │               │
│  ┌──────────▼────────────┐  │
│  │      FSMManager       │  │  ← WARMUP → DRILL → ROLEPLAY
│  └──────────┬────────────┘  │
│             │               │
│  ┌──────────▼────────────┐  │
│  │    JevGovernor        │  │  ← Noul, Choice, Score
│  │   sub-150 ms eval     │  │
│  └───────────────────────┘  │
│             │               │
│  ┌──────────▼────────────┐  │
│  │   E2E Speech Engine   │  │
│  │   (external service)  │  │
│  └───────────────────────┘  │
└─────────────────────────────┘
```

---

## 3. System 2: E2E Full-Duplex Speech Engine

Responsibilities:

- Capture raw PCM microphone audio from the browser.
- Transcribe user speech incrementally.
- Maintain a conversational context window.
- Generate Socratic tutor responses.
- Synthesize and stream tutor voice back to the browser.

Non-responsibilities:

- Deciding lesson phase transitions.
- Detecting curriculum drift.
- Emitting hard interrupts.

The E2E engine is treated as a stateful black box from the backend's perspective. The backend keeps a lightweight text summary so that it can reset or flush the engine without losing pedagogical continuity.

---

## 4. System 1: TypeSafe / Jev Governor

The Jev Governor is a thin, async wrapper around a typed evaluation service. It runs in non-blocking background tasks and never blocks the audio duplex stream. It returns one of three schema types:

### 4.1 `Noul` — Drift / Entity Check

Determines whether the current transcript refers to an allowed entity, topic, or vocabulary target.

```python
class NoulResult(BaseModel):
    drift_detected: bool
    target_match: list[str]
    confidence: float
```

### 4.2 `Choice` — FSM State Decision

Selects the next finite-state-machine phase given the current phase, transcript, and summary.

```python
class ChoiceResult(BaseModel):
    next_state: Literal["WARMUP", "DRILL", "ROLEPLAY", "PAUSE", "WRAPUP"]
    transition_reason: str
    required_vocabulary: list[str]
```

### 4.3 `Score` — Socratic Compliance

Scores how well the tutor's last response followed Socratic norms (question-led, non-directive, scaffolded).

```python
class ScoreResult(BaseModel):
    socratic_score: float  # 0.0 .. 1.0
    directive_detected: bool
    interrupt_recommended: bool
```

All three evaluations run concurrently. If any of them requests an interrupt or a state change, the backend emits an out-of-band control frame within <200 ms.

---

## 5. FSM State Transitions

The `FSMManager` tracks the current lesson phase.

```text
WARMUP
   │  (greeting + target vocabulary introduced)
   ▼
DRILL
   │  (repetition, substitution, pronunciation check)
   ▼
ROLEPLAY
   │  (open-ended scenario using target vocabulary)
   ▼
WRAPUP
```

Safe transitions:

- `WARMUP` → `DRILL`
- `DRILL` → `ROLEPLAY`
- `ROLEPLAY` → `WRAPUP`
- Any state → `PAUSE` (on hardware interrupt or user request)
- `PAUSE` → previous state (on resume)

Invalid transitions are rejected by the Jev `Choice` evaluation and logged, but the audio stream continues uninterrupted unless the invalid transition represents drift.

---

## 6. 3-Minute Milestone Audio Token Flush Strategy

E2E speech engines accumulate KV caches for audio tokens, causing latency and memory growth. Every 3 minutes of wall-clock lesson time, the backend performs a flush:

1. **Persist**: the current text summary (vocabulary used, mistakes, phase, goals) is saved into `FSMManager.context_summary`.
2. **Drop**: raw audio KV caches in the E2E engine are dropped.
3. **Re-prime**: the engine is restarted with the persisted text summary as its context.
4. **Continue**: the user notices at most a brief pause.

This strategy bounds memory without losing pedagogical state.

---

## 7. Out-of-Band Jev Evaluation & Interrupts

The WebSocket carries two frame types:

- **Binary frames**: raw audio bytes (client → server) and synthesized audio bytes (server → client).
- **JSON control frames**: transcripts, state changes, interrupts, and metadata.

When the Jev Governor detects drift or a directive tutor response, the backend emits a control frame:

```json
{
  "type": "INTERRUPT_SIGNAL",
  "source": "jev_score",
  "reason": "directive_detected",
  "target_state": "DRILL",
  "payload": { "corrective_prompt": "Try asking the student a question instead." }
}
```

On the client:

- `useDuplexSocket` parses control frames.
- `LessonRoom` stops playing the current tutor audio buffer.
- `VisualAssistOverlay` (if pulled open) displays the corrective hint.

The interrupt path is optimized for sub-200 ms end-to-end latency.

---

## 8. Data Flow

1. Browser captures microphone PCM via `useAudioRecorder`.
2. PCM chunks are sent as binary WebSocket frames to `/ws/audio-tutor`.
3. Backend forwards audio to E2E engine and receives incremental transcripts.
4. Backend spawns async Jev evaluation (`Noul`, `Choice`, `Score`).
5. E2E engine streams synthesized tutor audio back to the browser as binary frames.
6. If Jev detects an issue, a JSON `INTERRUPT_SIGNAL` or `STATE_CHANGE` frame preempts the audio stream.
7. Browser applies the command and continues the duplex stream.

---

## 9. Technology Choices

- **Backend**: FastAPI + Uvicorn for native async WebSocket handling.
- **Frontend**: Next.js 14 (App Router) + TypeScript + Tailwind CSS.
- **Audio**: Web Audio API on the client, PCM 16-bit 16 kHz mono by default.
- **State**: backend FSM owns canonical lesson state; client is a thin renderer.
- **Guardrails**: TypeSafe / Jev via typed Pydantic schemas and async HTTP calls.
