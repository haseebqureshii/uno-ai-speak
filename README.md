# Audio-First Socratic Language Learning Web App

## Executive Summary

An audio-first, drift-free Socratic language tutoring platform. The application pairs a low-latency end-to-end (E2E) full-duplex speech engine with a deterministic System 1 guardrail — the TypeSafe / Jev Governor — to keep every lesson on track. Students learn by speaking, receiving immediate voice feedback, and getting interrupted only when the lesson drifts outside safe pedagogical bounds.

Key characteristics:

- **Audio-first**: the primary input and output channel is natural speech, not typing.
- **Socratic**: the tutor asks leading questions rather than lecturing.
- **Drift-free**: the Jev Governor evaluates every turn in <150 ms for topic drift, FSM state correctness, and Socratic compliance.
- **Deterministic guardrails**: System 1 does not generate content; it validates boundaries and emits `INTERRUPT_SIGNAL` or `STATE_CHANGE` commands.
- **Scalable scaffolding**: FastAPI + WebSockets backend, Next.js + Tailwind + TypeScript frontend.

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- Node.js 20+ and pnpm (or npm)
- Access to an E2E speech API endpoint and a TypeSafe / Jev evaluation endpoint

### Backend

```bash
cd backend
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The WebSocket tutor endpoint is available at:

```
ws://localhost:8000/ws/audio-tutor
```

### Frontend

```bash
cd frontend
pnpm install
pnpm run dev
```

Open [http://localhost:3000](http://localhost:3000) and start a lesson from the home page.

---

## Environment Variables

Copy `.env.example` to `.env` in both `backend/` and `frontend/` and fill in the values.

| Variable | Location | Description |
| --- | --- | --- |
| `E2E_SPEECH_API_KEY` | backend | API key for the full-duplex E2E speech engine. |
| `E2E_SPEECH_ENDPOINT` | backend | Base URL for the E2E speech API. |
| `TYPESAFE_JEV_API_KEY` | backend | API key for the TypeSafe / Jev governor service. |
| `TYPESAFE_JEV_ENDPOINT` | backend | Base URL for the Jev evaluation endpoint. |
| `FRONTEND_ORIGIN` | backend | Allowed CORS origin for the frontend (`http://localhost:3000`). |
| `NEXT_PUBLIC_TUTOR_WS_URL` | frontend | WebSocket URL to reach `/ws/audio-tutor`. |
| `NEXT_PUBLIC_E2E_API_URL` | frontend | Optional direct E2E speech API URL for client-side fallback. |

---

## Quick Architecture Pointer

For the complete design, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

- **System 2** — E2E speech engine: listens, understands, generates natural voice responses.
- **System 1** — Jev Governor: deterministic, typed, sub-150 ms evaluator that guards state, drift, and Socratic form.
- **FSMManager** — tracks lesson phases (`WARMUP` → `DRILL` → `ROLEPLAY`) and vocabulary targets.
- **3-minute flush** — raw audio KV caches are dropped while text summaries persist, bounding memory and latency.

---

## License

MIT
