# Lesson Flow Update: Coach Alex Speaks First

## Overview

The lesson now starts with **Coach Alex speaking first** (in the home language), displaying both audio and captions on screen, before prompting the user to respond.

---

## New User Experience

### Before (Old Flow)
```
1. User enters /lesson
2. Microphone starts immediately
3. User hears silence, confused
4. User has to speak first
```

### After (New Flow)
```
1. User enters /lesson
2. **LessonIntro screen appears**
3. **Coach Alex speaks** (audio + captions visible)
4. Coach welcomes in home language, then transitions to target language
5. **User sees "Ready for you to speak"**
6. User clicks "Start Practicing"
7. Microphone activates
8. User responds
```

---

## Architecture Changes

### Frontend

#### New Component: `LessonIntro.tsx`
- **Purpose**: Display Coach Alex's opening message before user interaction
- **Features**:
  - Animated coach avatar (pulsing while speaking)
  - Real-time transcript display
  - Status badges (speaking → ready)
  - Connection and microphone indicators
  - "Skip intro" button
  - "Start Practicing" button (appears after coach finishes)

#### Updated: `lesson/page.tsx`
- Added `showIntro` state
- Renders `LessonIntro` first
- Transitions to `LessonRoom` after intro completes

#### Updated: `LessonRoom.tsx`
- Microphone no longer auto-starts on mount
- Waits for `LessonIntro` to complete
- Prevents duplicate audio context initialization

### Backend

#### Updated: `bridges/gemini.py`
**Cold-start trigger now includes:**
```
"Hello! Welcome to your [target_language] lesson. I'm Coach Alex, your Socratic language tutor.

In this session, we'll practice [target_language] through a realistic conversation.

I'm going to start our roleplay now. I'll speak first, then it'll be your turn to respond.

Here we go: [opening_line in target language]"
```

#### Updated: `fsm.py`
**System prompt now includes:**
```
- **IMPORTANT**: Begin the session by speaking in [home_language] to welcome the student, 
  then transition to [target_language] for the lesson.
```

---

## Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. User navigates to /lesson                                │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. LessonPage renders LessonIntro                           │
│    - WebSocket connects to backend                          │
│    - SETUP frame sent                                       │
│    - AudioContext initialized                               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Backend creates GeminiAudioBridge                        │
│    - Connects to Gemini Live API                            │
│    - Sends setup with Coach Alex persona                    │
│    - Receives setupComplete                                 │
│    - Sends cold-start trigger (in home language)            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Gemini synthesizes audio response                        │
│    - Speaks welcome in home language                        │
│    - Transitions to target language                         │
│    - Delivers opening line                                  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Audio streams to LessonIntro                             │
│    - Audio chunks decoded and played                        │
│    - Transcript displayed on screen                         │
│    - Avatar pulses while speaking                           │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Coach finishes speaking                                  │
│    - Audio queue empty                                      │
│    - Status changes to "Ready for you to speak"             │
│    - "Start Practicing" button appears                      │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. User clicks "Start Practicing"                           │
│    - LessonIntro completes                                  │
│    - LessonRoom renders                                     │
│    - Microphone activates                                   │
│    - User can now speak                                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Files Modified

### Frontend (3 files)
1. **`frontend/src/components/LessonIntro.tsx`** (NEW)
   - Intro screen with coach avatar
   - Audio playback queue
   - Transcript display
   - Status indicators
   - ~220 lines

2. **`frontend/src/app/lesson/page.tsx`**
   - Added `showIntro` state
   - Conditional rendering (Intro → Room)
   - Theme toggle in both screens

3. **`frontend/src/components/LessonRoom.tsx`**
   - Microphone start delayed until after intro
   - Added `isRecording` check

### Backend (2 files)
1. **`backend/bridges/gemini.py`**
   - Enhanced cold-start trigger with home language intro
   - Multi-paragraph welcome message
   - Clear transition to target language

2. **`backend/fsm.py`**
   - System prompt updated to instruct Coach Alex to speak home language first
   - Added emphasis marker for the intro requirement

---

## Expected Behavior

### LessonIntro Screen
```
┌──────────────────────────────────────┐
│          Welcome to Your Lesson      │
│        Spanish • Level A1            │
│                                      │
│           🎙️ (pulsing)              │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ 🗣️ Coach Alex is speaking...  │  │
│  │                                │  │
│  │ "Hello! Welcome to your        │  │
│  │ Spanish lesson. I'm Coach Alex │  │
│  │ your Socratic language tutor.  │  │
│  │                                │  │
│  │ In this session, we'll practice│  │
│  │ Spanish through a realistic    │  │
│  │ conversation...                │  │
│  │                                │  │
│  │ ¡Hola! Buenos días, ¿qué le   │  │
│  │ pongo?                         │  │
│  └────────────────────────────────┘  │
│                                      │
│  Connection: ✓ Connected             │
│  Microphone: ⏸️ Waiting              │
│                                      │
│  [Skip intro]                        │
└──────────────────────────────────────┘
```

### After Coach Finishes
```
┌──────────────────────────────────────┐
│          Welcome to Your Lesson      │
│        Spanish • Level A1            │
│                                      │
│           🎙️ (static)               │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ ✓ Ready for you to speak      │  │
│  │                                │  │
│  │ **Microphone is active.**     │  │
│  │ You can now speak and respond │  │
│  │ to Coach Alex.                 │  │
│  └────────────────────────────────┘  │
│                                      │
│  Connection: ✓ Connected             │
│  Microphone: ✓ Active               │
│                                      │
│  [Start Practicing →]                │
└──────────────────────────────────────┘
```

---

## Testing Checklist

- [ ] Open `http://localhost:3000`
- [ ] Complete onboarding (Spanish, English, A1)
- [ ] Click "Start Lesson"
- [ ] **Verify**: LessonIntro screen appears
- [ ] **Verify**: Coach avatar pulses
- [ ] **Verify**: "Coach Alex is speaking..." badge shows
- [ ] **Verify**: Audio plays (welcome in English)
- [ ] **Verify**: Transcript appears on screen
- [ ] **Verify**: Coach transitions to Spanish ("¡Hola!...")
- [ ] **Verify**: After audio ends, badge changes to "Ready for you to speak"
- [ ] **Verify**: "Start Practicing" button appears
- [ ] Click "Start Practicing"
- [ ] **Verify**: LessonRoom appears
- [ ] **Verify**: Microphone is active
- [ ] **Verify**: Can speak and hear responses

---

## Backend Logs (Expected)

```
[INFO] gemini-bridge: → Sending cold-start clientContent to Gemini:
[INFO] gemini-bridge: Trigger text (287 chars): Hello! Welcome to your Spanish lesson. I'm Coach Alex...
[INFO] gemini-bridge: ✓ Cold-start trigger sent successfully
[INFO] gemini-bridge: ✓ Received setupComplete from Gemini
[DEBUG] gemini-bridge: ← Received audio chunk from Gemini: 4800 bytes
[DEBUG] gemini-bridge: ← Received audio chunk from Gemini: 4800 bytes
... (multiple audio chunks)
```

---

## Browser Console Logs (Expected)

```
[LessonIntro] Control message: STATE_CHANGE session_initialized
[WebSocket] AUDIO_CHUNK: 7372 chars base64
[LessonIntro] Coach Alex finished speaking
[LessonIntro] Starting microphone - waiting for user input
[AudioRecorder] ✓ Microphone access granted
[AudioRecorder] ✓ Recording started successfully
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Coach doesn't speak | Check `GEMINI_API_KEY` is set |
| Audio plays but no transcript | Check WebSocket connection in browser console |
| Microphone doesn't activate | Click "Start Practicing" button |
| Intro stuck on "Connecting..." | Check backend is running on port 8000 |
| Coach speaks in wrong language | Verify `home_language` in SETUP payload |

---

## Next Steps (Optional Enhancements)

1. **Real-time captioning**: Stream transcript as Coach speaks (requires Gemini text response)
2. **Progress bar**: Show intro completion percentage
3. **Sound effects**: Subtle chime when coach finishes
4. **Accessibility**: Add ARIA live regions for screen readers
5. **Configurable**: Make intro length/timing adjustable in settings

---

**Status**: ✅ Implementation Complete  
**Tested**: Pending user verification  
**Version**: 0.3.0
