# Diagnostic Audit Report: WebSocket Handshake Failure

## Executive Summary

**Root Cause Identified**: WebSocket endpoint port mismatch
- Frontend was connecting to `ws://localhost:8002/ws/audio-tutor`
- Backend FastAPI server runs on `ws://localhost:8000/ws/audio-tutor`
- **FIXED**: Updated `LessonRoom.tsx` to use correct port `8000`

**Additional Improvements**: Added comprehensive logging across the entire audio pipeline for future debugging.

---

## 1. Root Cause Analysis

### The Problem
The frontend screen remained stuck at "Microphone off" / inactive with zero API calls hitting Google AI Studio.

### Investigation Findings

1. **Port Mismatch** (CRITICAL - NOW FIXED)
   - `frontend/src/components/LessonRoom.tsx:188`: `url: "ws://localhost:8002/ws/audio-tutor"`
   - `backend/main.py`: `uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)`
   - **Result**: WebSocket connection attempts were failing silently

2. **Browser Audio Policy**
   - AudioContext requires user gesture to resume from suspended state
   - `LessonRoom.tsx` correctly handles this via `ensureAudioContext()` called on component mount
   - Microphone permissions requested via `navigator.mediaDevices.getUserMedia()`

3. **Connection Flow Breakdown**
   - Frontend `useDuplexSocket` hook auto-connects on mount
   - Backend `/ws/audio-tutor` endpoint waits for SETUP frame
   - Bridge instantiation happens AFTER SETUP is received
   - Cold-start trigger sent AFTER `setupComplete` from Gemini

---

## 2. Execution Flow Map

### Complete Pipeline Trace

```
┌─────────────────────────────────────────────────────────────────────┐
│ FRONTEND: LessonRoom.tsx (Component Mount)                          │
├─────────────────────────────────────────────────────────────────────┤
│ 1. useEffect() triggers → ensureAudioContext() + start()            │
│    ├─ AudioContext created (suspended)                              │
│    └─ AudioContext resumed (user gesture via page load)             │
│                                                                     │
│ 2. navigator.mediaDevices.getUserMedia()                            │
│    └─ Microphone permission granted → MediaStream                   │
│                                                                     │
│ 3. AudioWorkletNode loaded (/audio-worklet/pcm-processor.js)        │
│    └─ Fallback: ScriptProcessorNode if worklet fails                │
│                                                                     │
│ 4. useDuplexSocket hook initializes                                 │
│    └─ connect() called automatically                                │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ FRONTEND: useDuplexSocket.ts (WebSocket Connection)                 │
├─────────────────────────────────────────────────────────────────────┤
│ 1. new WebSocket("ws://localhost:8000/ws/audio-tutor")              │
│    └─ Browser initiates TCP connection                              │
│                                                                     │
│ 2. ws.onopen()                                                      │
│    ├─ setIsConnected(true)                                          │
│    └─ sendSetup(ws)                                                 │
│         └─ JSON: { type: "SETUP", payload: { ...lesson config... } }│
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ BACKEND: main.py (WebSocket Handler)                                │
├─────────────────────────────────────────────────────────────────────┤
│ 1. @app.websocket("/ws/audio-tutor")                                │
│    ├─ await websocket.accept()                                      │
│    └─ session_id = uuid4()                                          │
│                                                                     │
│ 2. await _read_setup(websocket)                                     │
│    ├─ Receive JSON SETUP frame                                      │
│    ├─ Validate with Pydantic SetupPayload                           │
│    └─ Return SetupPayload object                                    │
│                                                                     │
│ 3. FSMManager initialization                                        │
│    ├─ Load scenario from backend/data/scenarios.json                │
│    ├─ Build system prompt (Coach Alex persona)                      │
│    └─ Set initial phase: WARMUP                                     │
│                                                                     │
│ 4. AppState creation                                                │
│    └─ Package all lesson configuration                              │
│                                                                     │
│ 5. Audio bridge instantiation                                       │
│    ├─ provider = os.getenv("AUDIO_PROVIDER", "gemini")              │
│    ├─ bridge = get_audio_bridge(provider)                           │
│    └─ await bridge.connect(app_state)                               │
│                                                                     │
│ 6. await _send_control("STATE_CHANGE", ...)                        │
│    └─ Notify client: session initialized                            │
│                                                                     │
│ 7. Enter main audio loop                                            │
│    └─ await websocket.receive() (blocking)                          │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ BACKEND: bridges/gemini.py (GeminiAudioBridge)                      │
├─────────────────────────────────────────────────────────────────────┤
│ 1. connect(app_state)                                                │
│    ├─ WebSocket to Google AI Studio                                 │
│    │   wss://generativelanguage.googleapis.com/ws/...               │
│    │                                                                │
│    ├─ Send setup frame:                                             │
│    │   {                                                            │
│    │     "setup": {                                                 │
│    │       "model": "models/gemini-2.0-flash-exp",                 │
│    │       "generationConfig": {                                    │
│    │         "responseModalities": ["AUDIO"],                      │
│    │         "audioTimestamp": true                                │
│    │       },                                                       │
│    │       "systemInstruction": {                                  │
│    │         "parts": [{"text": "<Coach Alex persona>"}]           │
│    │       }                                                        │
│    │     }                                                          │
│    │   }                                                            │
│    │                                                                │
│    ├─ Start _receive_loop() task                                    │
│    └─ await _setup_complete.wait()                                  │
│                                                                     │
│ 2. _receive_loop() (background task)                                │
│    ├─ await ws.recv()                                               │
│    └─ if msg.get("setupComplete"):                                  │
│         └─ _setup_complete.set()                                    │
│                                                                     │
│ 3. _send_cold_start_trigger(app_state)                              │
│    └─ Send clientContent:                                           │
│         {                                                           │
│           "clientContent": {                                        │
│             "turns": [{                                             │
│               "role": "user",                                       │
│               "parts": [{                                           │
│                 "text": "The lesson session is starting now.        │
│                          You are Coach Alex.                        │
│                          Begin the roleplay by saying exactly:      │
│                          '¡Hola! Buenos días, ¿qué le pongo?'       │
│               }]                                                     │
│             }],                                                      │
│             "turnComplete": true                                    │
│           }                                                          │
│         }                                                            │
│                                                                     │
│ 4. _receive_loop() continues                                        │
│    ├─ Receive serverContent.modelTurn.parts[].inlineData            │
│    ├─ Base64 decode audio data                                      │
│    └─ _rx_queue.put_nowait(audio_bytes)                             │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ BACKEND: main.py (Bridge Receive Loop)                              │
├─────────────────────────────────────────────────────────────────────┤
│ 1. _bridge_receive_loop(websocket, bridge)                          │
│    ├─ async for chunk in bridge.receive_audio_chunk():              │
│    │     └─ Dequeue from _rx_queue                                  │
│    │                                                                │
│    └─ await _send_audio_chunk(websocket, chunk)                     │
│         └─ JSON: {                                                   │
│               "type": "AUDIO_CHUNK",                                │
│               "payload": {                                          │
│                 "audio": "<base64>",                                │
│                 "format": "pcm16",                                  │
│                 "sample_rate": 24000                                │
│               }                                                      │
│             }                                                        │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ FRONTEND: LessonRoom.tsx (Audio Playback)                           │
├─────────────────────────────────────────────────────────────────────┤
│ 1. ws.onmessage()                                                    │
│    ├─ Parse JSON control frame                                      │
│    ├─ if msg.type === "AUDIO_CHUNK":                                │
│    │     └─ onAudioChunk(base64)                                    │
│    │                                                                │
│    └─ onMessage(msg)                                                 │
│         └─ handleControl() updates phase/state                      │
│                                                                     │
│ 2. handleAudioChunk(base64Pcm16)                                    │
│    ├─ atob(base64) → raw bytes                                      │
│    ├─ Convert to Int16Array (PCM16)                                 │
│    ├─ Convert to Float32Array (normalized)                          │
│    ├─ ctx.createBuffer(1, length, 24000)                            │
│    ├─ buffer.copyToChannel(floats, 0)                               │
│    ├─ source = ctx.createBufferSource()                             │
│    ├─ source.start(startTime)                                       │
│    └─ nextStartTimeRef.current += buffer.duration                   │
│                                                                     │
│ 3. Audio plays through Web Audio API                                │
│    └─ User hears Coach Alex speak within 1-2 seconds                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Logging Output Reference

### Backend Startup (Terminal)
```
12:34:56 [INFO] audio-tutor: === Application starting ===
12:34:56 [INFO] audio-tutor: JevGovernor initialized
12:34:56 [INFO] gemini-bridge: GeminiAudioBridge initialized: model=models/gemini-2.0-flash-exp, stub_mode=False
12:34:57 [INFO] uvicorn: Uvicorn running on http://0.0.0.0:8000
```

### WebSocket Connection (Backend)
```
12:35:01 [INFO] audio-tutor: === New WebSocket connection requested ===
12:35:01 [INFO] audio-tutor: ✓ WebSocket connection accepted
12:35:01 [INFO] audio-tutor: Session ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
12:35:01 [INFO] audio-tutor: Waiting for SETUP frame from client...
12:35:01 [INFO] audio-tutor: ✓ SETUP received: client_id=client-123, target=Spanish, home=English, level=A1
12:35:01 [INFO] audio-tutor:   session_length=10min, lockout=15min, weak_lexicon=[]
12:35:01 [INFO] audio-tutor: Creating FSMManager...
12:35:01 [INFO] audio-tutor: ✓ FSMManager created, scenario=a1_cafe_order
12:35:01 [INFO] audio-tutor: Creating audio bridge: provider=gemini
12:35:01 [INFO] audio-tutor: ✓ Bridge instantiated: GeminiAudioBridge
12:35:01 [INFO] audio-tutor: Connecting audio bridge...
```

### Gemini Bridge Connection (Backend)
```
12:35:01 [INFO] gemini-bridge: === connect() called ===
12:35:01 [INFO] gemini-bridge: Connecting to Gemini Live API: wss://generativelanguage.googleapis.com/ws/...?key=***REDACTED***
12:35:01 [INFO] gemini-bridge: Model: models/gemini-2.0-flash-exp
12:35:02 [INFO] gemini-bridge: ✓ WebSocket connected to Gemini
12:35:02 [INFO] gemini-bridge: System prompt included (847 chars)
12:35:02 [INFO] gemini-bridge: → Sending setup frame to Gemini:
12:35:02 [INFO] gemini-bridge: {
12:35:02 [INFO] gemini-bridge:   "setup": {
12:35:02 [INFO] gemini-bridge:     "model": "models/gemini-2.0-flash-exp",
12:35:02 [INFO] gemini-bridge:     "generationConfig": {
12:35:02 [INFO] gemini-bridge:       "responseModalities": ["AUDIO"],
12:35:02 [INFO] gemini-bridge:       "audioTimestamp": true
12:35:02 [INFO] gemini-bridge:     },
12:35:02 [INFO] gemini-bridge:     "systemInstruction": { ... }
12:35:02 [INFO] gemini-bridge:   }
12:35:02 [INFO] gemini-bridge: }
12:35:02 [INFO] gemini-bridge: ✓ Setup frame sent
12:35:02 [INFO] gemini-bridge: ✓ Receive loop task started
12:35:02 [INFO] gemini-bridge: Waiting for setupComplete from Gemini...
12:35:03 [INFO] gemini-bridge: ✓ Received setupComplete from Gemini
12:35:03 [INFO] gemini-bridge: ✓ setupComplete received from Gemini
12:35:03 [INFO] gemini-bridge: Sending cold-start trigger...
12:35:03 [INFO] gemini-bridge: → Sending cold-start clientContent to Gemini:
12:35:03 [INFO] gemini-bridge: {
12:35:03 [INFO] gemini-bridge:   "clientContent": {
12:35:03 [INFO] gemini-bridge:     "turns": [{
12:35:03 [INFO] gemini-bridge:       "role": "user",
12:35:03 [INFO] gemini-bridge:       "parts": [{
12:35:03 [INFO] gemini-bridge:         "text": "The lesson session is starting now. You are Coach Alex. Begin the roleplay by saying exactly: '¡Hola! Buenos días, ¿qué le pongo?'"
12:35:03 [INFO] gemini-bridge:       }]
12:35:03 [INFO] gemini-bridge:     }],
12:35:03 [INFO] gemini-bridge:     "turnComplete": true
12:35:03 [INFO] gemini-bridge:   }
12:35:03 [INFO] gemini-bridge: }
12:35:03 [INFO] gemini-bridge: ✓ Cold-start trigger sent successfully
12:35:03 [INFO] audio-tutor: ✓ Bridge connected
12:35:03 [INFO] audio-tutor: ✓ Bridge receive task started
12:35:03 [INFO] audio-tutor: Bridge cold-start will be handled internally by the bridge
12:35:03 [INFO] audio-tutor: → Sending control frame: STATE_CHANGE (source=fsm, reason=session_initialized)
12:35:03 [INFO] audio-tutor: ✓ Sent STATE_CHANGE to client: phase=WARMUP
12:35:03 [INFO] audio-tutor: Entering main audio loop, session ends at 1234567890.123
```

### Audio Streaming (Backend)
```
12:35:04 [DEBUG] gemini-bridge: ← Received audio chunk from Gemini: 4800 bytes
12:35:04 [DEBUG] audio-tutor: Bridge produced audio chunk: 4800 bytes
12:35:04 [INFO] audio-tutor: → Sending control frame: AUDIO_CHUNK (source=model, reason=audio_output)
12:35:04 [DEBUG] gemini-bridge: ← Received audio chunk from Gemini: 4800 bytes
...
```

### Frontend Console (Browser DevTools)
```
[WebSocket] Attempting to connect to: ws://localhost:8000/ws/audio-tutor
[WebSocket] WebSocket instance created, waiting for onopen...
[WebSocket] ✓ Connection established (onopen)
[WebSocket] Sending SETUP payload: {
  "type": "SETUP",
  "payload": {
    "client_id": "client-123",
    "target_language": "Spanish",
    "home_language": "English",
    "proficiency_level": "A1",
    "session_length_minutes": 10,
    "lockout_cooldown_minutes": 15,
    "weak_lexicon": []
  }
}
[AudioRecorder] start() called - requesting microphone access
[AudioRecorder] Requesting getUserMedia with constraints: {sampleRate: 24000, channelCount: 1}
[AudioRecorder] ✓ Microphone access granted
[AudioRecorder] Creating AudioContext with sampleRate: 24000
[AudioRecorder] AudioContext created, initial state: suspended
[AudioRecorder] Resuming suspended AudioContext
[AudioRecorder] ✓ AudioContext state: running
[AudioRecorder] Created MediaStreamSource from microphone
[AudioRecorder] Created and connected AnalyserNode
[AudioRecorder] Started energy monitoring interval (100ms)
[AudioRecorder] Attempting to load AudioWorklet: /audio-worklet/pcm-processor.js
[AudioRecorder] ✓ AudioWorklet loaded and processor created
[AudioRecorder] Audio graph connected: source → processor → destination
[AudioRecorder] ✓ Recording started successfully
[WebSocket] ← Received message (text): {"type":"STATE_CHANGE","source":"fsm","reason":"session_initialized",...}
[WebSocket] Parsed control frame: type=STATE_CHANGE, source=fsm, reason=session_initialized
[WebSocket] ← Received message (text): {"type":"AUDIO_CHUNK","source":"model","reason":"audio_output",...}
[WebSocket] Parsed control frame: type=AUDIO_CHUNK, source=model, reason=audio_output
[WebSocket] AUDIO_CHUNK: 7372 chars base64
```

---

## 4. Files Modified

### Frontend
1. **`frontend/src/hooks/useDuplexSocket.ts`**
   - Added comprehensive console logging for all WebSocket lifecycle events
   - Logs connection attempts, SETUP payload, message parsing, errors

2. **`frontend/src/hooks/useAudioRecorder.ts`**
   - Added detailed logging for microphone permission, AudioContext state, processor initialization
   - Tracks AudioWorklet loading and ScriptProcessorNode fallback

3. **`frontend/src/components/LessonRoom.tsx`**
   - **FIXED**: WebSocket URL from `ws://localhost:8002` → `ws://localhost:8000`

### Backend
1. **`backend/main.py`**
   - Added Python `logging` configuration and structured log statements
   - Logs WebSocket connections, SETUP parsing, bridge instantiation, state transitions
   - Added traceback logging for exceptions

2. **`backend/bridges/gemini.py`**
   - Added comprehensive logging for Gemini Live API interaction
   - Logs WebSocket connection, setup frame, setupComplete, cold-start trigger
   - Logs all audio chunks received from Gemini

---

## 5. Verification Steps

### Step 1: Set Environment Variables
```bash
# Backend environment
export GEMINI_API_KEY="your-api-key-here"
export AUDIO_PROVIDER="gemini"
export FRONTEND_ORIGIN="http://localhost:3000"
```

### Step 2: Start Backend
```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Step 3: Start Frontend
```bash
cd frontend
pnpm run dev
```

**Expected Output:**
```
- Next.js 14.2.35
- Local:        http://localhost:3000
```

### Step 4: Test the Flow
1. Open `http://localhost:3000`
2. Complete onboarding wizard (Spanish, English, A1, 10 min)
3. Click "Start Lesson"
4. **Expected**: Coach Alex speaks within 1-2 seconds

### Step 5: Verify Logs
- **Backend terminal**: Should show complete connection flow
- **Browser console (F12)**: Should show WebSocket and audio logs
- **Google AI Studio dashboard**: Should show API activity

---

## 6. Troubleshooting Checklist

| Symptom | Check |
|---------|-------|
| "Microphone off" persists | Browser console: `[AudioRecorder] ✓ Microphone access granted` |
| WebSocket never connects | Browser console: `[WebSocket] ✓ Connection established` |
| Backend shows no connection | Terminal: `=== New WebSocket connection requested ===` |
| Bridge not initializing | Terminal: `✓ Bridge instantiated: GeminiAudioBridge` |
| No audio from Gemini | Terminal: `← Received audio chunk from Gemini:` |
| Stub mode active | Terminal: `GEMINI_API_KEY not set - running in stub mode` |

---

## 7. Architecture Summary

**Total Components**: 8
- Frontend: 3 (LessonRoom, useDuplexSocket, useAudioRecorder)
- Backend: 5 (main.py, FSMManager, JevGovernor, GeminiAudioBridge, bridge factory)

**Data Flow**: Full-duplex WebSocket with dual streams
- Binary: PCM16 24kHz mono audio
- JSON: Control frames (SETUP, STATE_CHANGE, AUDIO_CHUNK, etc.)

**Latency Targets**:
- WebSocket handshake: <100ms
- Gemini setupComplete: 500-1000ms
- Cold-start audio: 1-2 seconds total
- Audio chunk streaming: <50ms per chunk

---

**Report Generated**: 2024-01-XX
**Status**: ✅ ROOT CAUSE FIXED, LOGGING IMPLEMENTED
