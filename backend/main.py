"""
FastAPI WebSocket server for the Audio-First Socratic Language Learning Web App.

Routes:
- /ws/audio-tutor   full-duplex audio + JSON control stream
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("audio-tutor")

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from bridges import AppState, get_audio_bridge
from bridges.base import BaseAudioBridge
from fsm import FSMManager, LessonPhase
from jev_governor import ChoiceResult, JevGovernor, NoulResult, ScoreResult


class SetupPayload(BaseModel):
    """Configuration sent by the client during the initial WebSocket handshake."""

    client_id: str
    target_language: str
    home_language: str
    proficiency_level: str = Field(pattern=r"^(A1|A2|B1|B2|C1)$")
    session_length_minutes: int = Field(ge=5, le=60)
    lockout_cooldown_minutes: int = Field(default=15, ge=5, le=60)
    provider: str = Field(default="gemini", pattern=r"^(local|openai|gemini|stub)$")
    weak_lexicon: list[str] = Field(default_factory=list)


class ControlFrame(BaseModel):
    """Base schema for JSON control frames received from the client."""

    type: str
    payload: dict[str, Any] | None = None


class ServerControlFrame(BaseModel):
    """Schema for JSON control frames emitted by the server."""

    type: str
    source: str
    reason: str | None = None
    target_state: str | None = None
    payload: dict[str, Any] | None = None


# In-memory registries. Replace with Redis/Postgres in production.
SESSIONS: dict[str, FSMManager] = {}
LOCKOUT_REGISTRY: dict[str, datetime] = {}


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start guardrail service."""
    logger.info("=== Application starting ===")
    # API keys are optional in local dev; the JevGovernor stub works without them.
    app.state.jev = JevGovernor(api_key=os.getenv("TYPESAFE_JEV_API_KEY"))
    logger.info("JevGovernor initialized")
    yield
    logger.info("=== Application shutting down ===")
    SESSIONS.clear()
    LOCKOUT_REGISTRY.clear()


app = FastAPI(
    title="Audio-First Socratic Language Tutor",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_env("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_client_locked_out(client_id: str) -> datetime | None:
    """Return the active lockout expiry for a client, or None if not locked out."""
    expiry = LOCKOUT_REGISTRY.get(client_id)
    if expiry is None:
        return None
    if datetime.now(timezone.utc) >= expiry:
        LOCKOUT_REGISTRY.pop(client_id, None)
        return None
    return expiry


@app.websocket("/ws/audio-tutor")
async def audio_tutor_ws(websocket: WebSocket) -> None:
    """
    Full-duplex audio + control WebSocket.

    Binary frames: raw PCM from the client, synthesized PCM from the server.
    JSON frames: transcripts, state changes, interrupts, strike warnings, and metadata.
    """
    logger.info("=== New WebSocket connection requested ===")
    await websocket.accept()
    logger.info("✓ WebSocket connection accepted")
    session_id = str(uuid.uuid4())
    logger.info(f"Session ID: {session_id}")
    fsm: FSMManager | None = None
    bridge: BaseAudioBridge | None = None
    bridge_receive_task: asyncio.Task | None = None
    warmup_task: asyncio.Task | None = None
    jev: JevGovernor = websocket.app.state.jev

    # Welcome sequence: sent immediately after accept, before SETUP frame.
    await _send_control(
        websocket,
        "SESSION_START",
        source="server",
        reason="connection_accepted",
        target_state="WARMUP",
        payload={
            "sessionId": session_id,
            "state": "WARMUP",
            "strikeCount": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    await _send_control(
        websocket,
        "STATE_CHANGE",
        source="server",
        reason="warmup_started",
        target_state="WARMUP",
        payload={},
    )
    warmup_task = asyncio.create_task(_warmup_caption_loop(websocket))
    logger.info("✓ Warmup caption task started")

    try:
        # 1. Receive setup configuration before entering the audio loop.
        logger.info("Waiting for SETUP frame from client...")
        setup = await _read_setup(websocket)
        if setup is None:
            logger.warning("SETUP failed or invalid, closing connection")
            await websocket.close(code=1008)
            return

        logger.info(f"✓ SETUP received: client_id={setup.client_id}, target={setup.target_language}, home={setup.home_language}, level={setup.proficiency_level}")
        logger.info(f"  session_length={setup.session_length_minutes}min, lockout={setup.lockout_cooldown_minutes}min, weak_lexicon={setup.weak_lexicon}")

        # 2. Enforce global lockout before creating the session.
        active_lockout = _is_client_locked_out(setup.client_id)
        if active_lockout:
            logger.warning(f"Client {setup.client_id} is locked out until {active_lockout}")
            await _send_control(
                websocket,
                "LOCKOUT_SIGNAL",
                source="server",
                reason="client_is_locked_out",
                payload={
                    "lockout_until": active_lockout.isoformat(),
                    "remaining_seconds": int(
                        (active_lockout - datetime.now(timezone.utc)).total_seconds()
                    ),
                },
            )
            await websocket.close(code=1008)
            return

        # 3. Create the lesson session and the live audio model bridge.
        logger.info("Creating FSMManager...")
        fsm = FSMManager(
            session_id=session_id,
            client_id=setup.client_id,
            target_language=setup.target_language,
            home_language=setup.home_language,
            proficiency_level=setup.proficiency_level,
            session_length_minutes=setup.session_length_minutes,
            lockout_cooldown_minutes=setup.lockout_cooldown_minutes,
            weak_lexicon=setup.weak_lexicon,
        )
        logger.info(f"✓ FSMManager created, scenario={fsm.scenario.get('id', 'none')}")
        SESSIONS[session_id] = fsm

        app_state = AppState(
            session_id=session_id,
            client_id=setup.client_id,
            target_language=fsm.target_language,
            home_language=fsm.home_language,
            proficiency_level=fsm.proficiency_level,
            session_length_minutes=fsm.session_length_minutes,
            lockout_cooldown_minutes=fsm.lockout_cooldown_minutes,
            vocabulary=list(fsm.vocabulary),
            system_prompt=fsm.build_system_prompt(),
            scenario_id=fsm.scenario.get("id", ""),
            ai_role=fsm.scenario.get("ai_role", ""),
            user_task=fsm.scenario.get("user_task", ""),
            target_lexicon=list(fsm.scenario.get("target_lexicon", [])),
            opening_line=fsm.scenario.get("opening_line", ""),
            completion_conditions=list(fsm.scenario.get("completion_conditions", [])),
            weak_lexicon=list(fsm.weak_lexicon),
        )
        
        # Get audio bridge based on environment
        provider = os.getenv("AUDIO_PROVIDER", "gemini")
        logger.info(f"Creating audio bridge: provider={provider}")
        bridge = get_audio_bridge(provider)
        logger.info(f"✓ Bridge instantiated: {type(bridge).__name__}")
        
        logger.info("Connecting audio bridge...")
        await bridge.connect(app_state)
        logger.info("✓ Bridge connected")
        
        bridge_receive_task = asyncio.create_task(
            _bridge_receive_loop(websocket, bridge)
        )
        logger.info("✓ Bridge receive task started")

        # Cold-start is now handled internally by the bridge after setupComplete.
        # The bridge sends an initial clientContent turn to trigger Coach Alex's opening line.
        logger.info("Bridge cold-start will be handled internally by the bridge")

        await _send_control(
            websocket,
            "STATE_CHANGE",
            source="fsm",
            reason="session_initialized",
            target_state=fsm.phase.value,
            payload={
                "session_id": session_id,
                "scenario_id": app_state.scenario_id,
                "target_language": fsm.target_language,
                "home_language": fsm.home_language,
                "proficiency_level": fsm.proficiency_level,
                "vocabulary": fsm.vocabulary,
                "target_lexicon": app_state.target_lexicon,
                "opening_line": app_state.opening_line,
                "weak_lexicon": app_state.weak_lexicon,
            },
        )
        logger.info(f"✓ Sent STATE_CHANGE to client: phase={fsm.phase.value}")

        # 4. Main audio/control loop.
        session_end_at = time.monotonic() + fsm.session_length_minutes * 60
        last_flush_at = time.monotonic()
        FLUSH_INTERVAL_SECONDS = 180  # 3-minute milestone flush
        logger.info(f"Entering main audio loop, session ends at {session_end_at}")

        while time.monotonic() < session_end_at:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                logger.info("Client disconnected")
                # Client closed the connection cleanly or unexpectedly.
                break

            if "bytes" in message:
                logger.debug(f"Received audio frame: {len(message['bytes'])} bytes")
                await _handle_audio_frame(websocket, fsm, jev, message["bytes"], bridge)
            elif "text" in message:
                logger.debug(f"Received text frame: {message['text'][:100]}...")
                await _handle_text_frame(websocket, fsm, jev, message["text"], bridge, warmup_task)

            # Background 3-minute flush check.
            now = time.monotonic()
            if now - last_flush_at >= FLUSH_INTERVAL_SECONDS:
                await _perform_audio_flush(websocket, fsm)
                last_flush_at = now

        # Natural session end.
        if fsm.phase.value != "WRAPUP":
            try:
                fsm.transition("WRAPUP", reason="session_time_expired")
            except ValueError:
                pass
            await _send_control(
                websocket,
                "SESSION_ASSESSMENT",
                source="fsm",
                reason="session_completed",
                target_state="WRAPUP",
                payload={"data": fsm.evaluate_session(milestone_completed=False)},
            )
            await _send_control(
                websocket,
                "STATE_CHANGE",
                source="fsm",
                reason="session_completed",
                target_state="WRAPUP",
                payload={"final_summary": fsm.to_summary()},
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnect caught")
        pass
    except Exception as exc:
        logger.error(f"Unhandled exception in WebSocket handler: {type(exc).__name__}: {exc}")
        logger.error(traceback.format_exc())
        await _send_control(
            websocket,
            "ERROR",
            source="server",
            reason=f"unhandled_exception: {type(exc).__name__}: {exc}",
            payload={"recoverable": False},
        )
    finally:
        logger.info("Cleaning up session resources...")
        if fsm is not None:
            SESSIONS.pop(session_id, None)
        if bridge_receive_task is not None:
            try:
                bridge_receive_task.cancel()
                await bridge_receive_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if warmup_task is not None:
            try:
                warmup_task.cancel()
                await warmup_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if bridge is not None:
            try:
                await bridge.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("✓ Session cleanup complete")


async def _warmup_caption_loop(websocket: WebSocket) -> None:
    """Send a short sequence of sample caption updates during the warmup phase."""
    try:
        for i in range(1, 6):
            await asyncio.sleep(1.0)
            await _send_control(
                websocket,
                "CAPTION_UPDATE",
                source="server",
                reason="warmup_sample",
                payload={"index": i, "total": 5, "text": f"Sample caption {i}/5"},
            )
    except asyncio.CancelledError:
        logger.info("Warmup caption loop cancelled")
        raise


async def _read_setup(websocket: WebSocket) -> SetupPayload | None:
    """Read and validate the initial SETUP control frame from the client."""
    try:
        message = await websocket.receive_text()
        frame = ControlFrame.model_validate_json(message)
        if frame.type != "SETUP":
            await _send_control(
                websocket,
                "ERROR",
                source="server",
                reason="expected_setup_frame_first",
                payload={"recoverable": False},
            )
            return None
        return SetupPayload.model_validate(frame.payload or {})
    except ValidationError as exc:
        await _send_control(
            websocket,
            "ERROR",
            source="server",
            reason="invalid_setup_payload",
            payload={"detail": exc.errors(), "recoverable": False},
        )
        return None
    except Exception:
        return None


async def _handle_audio_frame(
    websocket: WebSocket,
    fsm: FSMManager,
    jev: JevGovernor,
    audio_bytes: bytes,
    bridge: BaseAudioBridge,
) -> None:
    """
    Handle a raw audio frame.

    The bytes are forwarded to the configured audio bridge (local, OpenAI,
    Gemini, or stub). The bridge is responsible for its own fallback audio,
    so main.py no longer emits placeholder audio directly.
    Guardrails run concurrently and do not block the duplex audio stream.
    """
    if fsm.is_lockout_active():
        return

    # Track the spoken turn without blocking; actual transcription is captured via
    # the optional USER_TRANSCRIPT control frame.
    fsm.record_user_audio_frame(len(audio_bytes))

    try:
        await bridge.send_audio_chunk(audio_bytes)
    except Exception as exc:
        await _send_control(
            websocket,
            "ERROR",
            source="bridge",
            reason=f"bridge_send_failed: {exc}",
            payload={"recoverable": True},
        )

    # Run Jev guardrails concurrently without blocking the duplex audio stream.
    transcript = f"[audio:{len(audio_bytes)} bytes]"
    asyncio.create_task(_run_guardrails(websocket, fsm, jev, transcript))


async def _handle_text_frame(
    websocket: WebSocket,
    fsm: FSMManager,
    jev: JevGovernor,
    text: str,
    bridge: BaseAudioBridge,
    warmup_task: asyncio.Task | None = None,
) -> None:
    """Parse and act on JSON control frames from the client."""
    try:
        frame = ControlFrame.model_validate_json(text)
    except ValidationError as exc:
        await _send_control(
            websocket,
            "ERROR",
            source="server",
            reason="invalid_control_frame",
            payload={"detail": exc.errors(), "recoverable": True},
        )
        return

    payload = frame.payload or {}

    if frame.type == "HARDWARE_INTERRUPT":
        try:
            await bridge.handle_interrupt()
        except Exception as exc:
            await _send_control(
                websocket,
                "ERROR",
                source="bridge",
                reason=f"interrupt_failed: {exc}",
                payload={"recoverable": True},
            )
        try:
            fsm.transition("PAUSE", reason="hardware_interrupt_from_client")
        except ValueError:
            pass
        await _send_control(
            websocket,
            "INTERRUPT_SIGNAL",
            source="client_hardware",
            reason="user_pressed_interrupt",
            target_state=fsm.phase.value,
            payload={},
        )
    elif frame.type == "RESUME":
        try:
            fsm.resume_from_pause()
        except ValueError:
            pass
        await _send_control(
            websocket,
            "STATE_CHANGE",
            source="fsm",
            reason="session_resumed",
            target_state=fsm.phase.value,
            payload={},
        )
    elif frame.type == "START_LESSON":
        if fsm.phase.value != "WARMUP":
            await _send_control(
                websocket,
                "ERROR",
                source="fsm",
                reason="start_lesson_only_allowed_in_warmup",
                target_state=fsm.phase.value,
                payload={"current_phase": fsm.phase.value},
            )
            return
        try:
            fsm.transition("DRILL", reason="start_lesson_from_client")
        except ValueError:
            pass
        if warmup_task is not None:
            warmup_task.cancel()
            try:
                await warmup_task
            except asyncio.CancelledError:
                pass
        await _send_control(
            websocket,
            "STATE_CHANGE",
            source="fsm",
            reason="lesson_started",
            target_state="DRILL",
            payload={},
        )
    elif frame.type == "PING":
        await _send_control(websocket, "PONG", source="server", reason="heartbeat")
    elif frame.type == "GET_HINT":
        await _send_control(
            websocket,
            "HINT_RESPONSE",
            source="fsm",
            reason="on_demand_hint",
            payload={
                "phase": fsm.phase.value,
                "vocabulary": fsm.vocabulary,
            },
        )
    elif frame.type == "USER_TRANSCRIPT":
        transcript = payload.get("text", "")
        if transcript:
            fsm.record_user_turn(transcript)
    elif frame.type == "DEBRIEF":
        if fsm.phase.value != "WRAPUP":
            try:
                fsm.transition("WRAPUP", reason="explicit_debrief")
            except ValueError:
                pass
        await _send_control(
            websocket,
            "SESSION_ASSESSMENT",
            source="fsm",
            reason="debrief_requested",
            target_state="WRAPUP",
            payload={"data": fsm.evaluate_session(milestone_completed=False)},
        )
        await _send_control(
            websocket,
            "STATE_CHANGE",
            source="fsm",
            reason="session_completed",
            target_state="WRAPUP",
            payload={"final_summary": fsm.to_summary()},
        )
    else:
        await _send_control(
            websocket,
            "ERROR",
            source="server",
            reason="unknown_control_type",
            payload={"received_type": frame.type, "recoverable": True},
        )


async def _run_guardrails(
    websocket: WebSocket,
    fsm: FSMManager,
    jev: JevGovernor,
    transcript: str,
) -> None:
    """Run Noul, Choice, and Score guardrails in parallel and emit commands."""
    # Once the session is in a terminal phase, guardrails have nothing to decide.
    if fsm.phase.value == "WRAPUP" or fsm.is_lockout_active():
        return

    try:
        noul_task = asyncio.create_task(jev.check_drift(transcript, fsm))
        choice_task = asyncio.create_task(jev.choose_state(fsm, transcript))
        score_task = asyncio.create_task(jev.score_tutor_response(fsm.last_tutor_text))

        noul, choice, score = await asyncio.gather(
            noul_task,
            choice_task,
            score_task,
            return_exceptions=True,
        )

        if any(isinstance(r, BaseException) for r in (noul, choice, score)):
            await _send_control(
                websocket,
                "ERROR",
                source="jev",
                reason="guardrail_evaluation_failed",
                payload={"recoverable": True},
            )
            return

        noul = NoulResult.model_validate(noul)
        choice = ChoiceResult.model_validate(choice)
        score = ScoreResult.model_validate(score)

        # 5-strikes penalty: deliberate off-topic / jailbreak with high confidence.
        if noul.is_off_topic and noul.confidence > JevGovernor.OFF_TOPIC_CONFIDENCE_THRESHOLD:
            await _apply_strike(websocket, fsm, noul)
            return

        # Drift or directive response → emit interrupt.
        if noul.drift_detected or score.directive_detected:
            await _send_control(
                websocket,
                "INTERRUPT_SIGNAL",
                source="jev_score" if score.directive_detected else "jev_noul",
                reason="drift_or_directive_detected",
                target_state=choice.next_state,
                payload={
                    "drift": noul.drift_detected,
                    "directive": score.directive_detected,
                    "socratic_score": score.socratic_score,
                    "corrective_prompt": (
                        "Let's get back to a question. Can you try again using one of the target words?"
                    ),
                },
            )
            return

        # State transition requested by Choice evaluation.
        if choice.next_state != fsm.phase.value:
            try:
                fsm.transition(choice.next_state, reason=choice.transition_reason)
            except ValueError:
                # A late-arriving guardrail result targeted an earlier phase.
                return
            await _send_control(
                websocket,
                "STATE_CHANGE",
                source="jev_choice",
                reason=choice.transition_reason,
                target_state=fsm.phase.value,
                payload={"required_vocabulary": choice.required_vocabulary},
            )

    except Exception as exc:
        await _send_control(
            websocket,
            "ERROR",
            source="jev",
            reason=f"guardrail_exception: {type(exc).__name__}",
            payload={"recoverable": True},
        )


async def _apply_strike(
    websocket: WebSocket,
    fsm: FSMManager,
    noul: NoulResult,
) -> None:
    """Increment the strike counter, emit warnings, and lock out at 5 strikes."""
    new_count = fsm.increment_strike()

    if new_count >= 5:
        lockout_until = fsm.apply_lockout()
        LOCKOUT_REGISTRY[fsm.client_id] = lockout_until
        await _send_control(
            websocket,
            "LOCKOUT_SIGNAL",
            source="jev_noul",
            reason="five_drift_strikes_reached",
            payload={
                "drift_strikes": new_count,
                "lockout_until": lockout_until.isoformat(),
                "lockout_cooldown_minutes": fsm.lockout_cooldown_minutes,
                "confidence": noul.confidence,
            },
        )
        return

    await _send_control(
        websocket,
        "STRIKE_WARNING",
        source="jev_noul",
        reason="off_topic_detected",
        payload={
            "drift_strikes": new_count,
            "max_strikes": 5,
            "confidence": noul.confidence,
            "admonition": (
                "Coach Alex here: let's stay focused on the lesson. "
                f"Off-topic input detected ({new_count}/5)."
            ),
            "audio_warning": "please_return_to_the_lesson",
        },
    )


async def _perform_audio_flush(websocket: WebSocket, fsm: FSMManager) -> None:
    """
    3-minute milestone flush.

    Persist text summary, drop raw audio KV caches, re-prime engine with summary.
    """
    if fsm.phase.value == "WRAPUP":
        return
    fsm.flush_audio_context()
    await _send_control(
        websocket,
        "STATE_CHANGE",
        source="fsm_flush",
        reason="three_minute_audio_flush",
        target_state=fsm.phase.value,
        payload={"context_summary": fsm.context_summary},
    )


async def _send_control(
    websocket: WebSocket,
    frame_type: str,
    source: str,
    reason: str | None = None,
    target_state: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Send a validated JSON control frame to the client if still connected."""
    if websocket.client_state != WebSocketState.CONNECTED:
        logger.debug(f"Cannot send {frame_type} - WebSocket not connected")
        return
    frame = ServerControlFrame(
        type=frame_type,
        source=source,
        reason=reason,
        target_state=target_state,
        payload=payload or {},
    )
    try:
        logger.info(f"→ Sending control frame: {frame_type} (source={source}, reason={reason})")
        await websocket.send_text(frame.model_dump_json())
    except (WebSocketDisconnect, RuntimeError) as exc:
        # Client already gone; no need to surface this as a server error.
        logger.debug(f"Failed to send {frame_type}: {exc}")
        pass


async def _send_audio_chunk(websocket: WebSocket, pcm16_bytes: bytes) -> None:
    """Send an AUDIO_CHUNK control frame containing base64 PCM16 audio."""
    await _send_control(
        websocket,
        "AUDIO_CHUNK",
        source="model",
        reason="audio_output",
        payload={"audio": base64.b64encode(pcm16_bytes).decode("ascii"), "format": "pcm16", "sample_rate": 24000},
    )


async def _bridge_receive_loop(websocket: WebSocket, bridge: BaseAudioBridge) -> None:
    """Forward audio chunks produced by the bridge to the WebSocket client."""
    logger.info("Bridge receive loop started")
    try:
        async for chunk in bridge.receive_audio_chunk():
            try:
                logger.debug(f"Bridge produced audio chunk: {len(chunk)} bytes")
                await _send_audio_chunk(websocket, chunk)
            except Exception as exc:
                # Client likely disconnected; stop consuming bridge audio.
                logger.debug(f"Failed to send audio chunk: {exc}")
                break
    except asyncio.CancelledError:
        # Task cancelled (client disconnect or session shutdown); stop cleanly.
        logger.info("Bridge receive loop cancelled")
        pass
    except Exception as exc:
        logger.error(f"Bridge receive loop failed: {type(exc).__name__}: {exc}")
        try:
            await _send_control(
                websocket,
                "ERROR",
                source="bridge",
                reason=f"receive_loop_failed: {type(exc).__name__}: {exc}",
                payload={"recoverable": True},
            )
        except Exception:
            pass
    logger.info("Bridge receive loop exited")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
