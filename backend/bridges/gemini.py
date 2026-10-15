"""Google Gemini Multimodal Live API audio bridge."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, AsyncGenerator

from .base import AppState, BaseAudioBridge, generate_sine_pcm16

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

logger = logging.getLogger("gemini-bridge")


class GeminiAudioBridge(BaseAudioBridge):
    """Bridge to the Google Gemini Multimodal Live API."""

    PROVIDER = "gemini"
    DEFAULT_MODEL = "gemini-2.0-flash-exp"
    SAMPLE_RATE = 24000

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        raw_model = model or os.getenv("GEMINI_MODEL") or self.DEFAULT_MODEL
        self.model = raw_model if raw_model.startswith("models/") else f"models/{raw_model}"
        self.ws: Any = None
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
        self._closed = False
        self._stub = not (self.api_key and self.api_key.strip())
        self._setup_complete = asyncio.Event()
        self._cold_start_sent = False
        
        logger.info(f"GeminiAudioBridge initialized: model={self.model}, stub_mode={self._stub}")
        if self._stub:
            logger.warning("GEMINI_API_KEY not set - running in stub mode")

    async def connect(self, fsm_state: AppState) -> None:
        logger.info("=== connect() called ===")
        if self._stub:
            logger.info("Stub mode - skipping connection")
            return
        if websockets is None:
            raise RuntimeError("websockets package is required for the Gemini audio bridge")

        # Construct WebSocket URL (redact API key in logs)
        uri = (
            "wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
            f"?key={self.api_key}"
        )
        redacted_uri = uri.replace(self.api_key, "***REDACTED***")
        logger.info(f"Connecting to Gemini Live API: {redacted_uri}")
        logger.info(f"Model: {self.model}")

        try:
            self.ws = await websockets.connect(uri)
            logger.info("✓ WebSocket connected to Gemini")
            
            # Build setup payload
            setup_payload: dict[str, Any] = {
                "setup": {
                    "model": self.model,
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "audioTimestamp": True,
                    },
                }
            }
            if fsm_state.system_prompt:
                setup_payload["setup"]["systemInstruction"] = {
                    "parts": [{"text": fsm_state.system_prompt}]
                }
                logger.info(f"System prompt included ({len(fsm_state.system_prompt)} chars)")
            
            logger.info("→ Sending setup frame to Gemini:")
            logger.info(json.dumps(setup_payload, indent=2)[:500] + "...")
            await self.ws.send(json.dumps(setup_payload))
            logger.info("✓ Setup frame sent")
            
            # Start receive loop
            self._recv_task = asyncio.create_task(self._receive_loop())
            logger.info("✓ Receive loop task started")
            
            # Wait for setupComplete before sending cold-start trigger
            logger.info("Waiting for setupComplete from Gemini...")
            await self._setup_complete.wait()
            logger.info("✓ setupComplete received from Gemini")
            
            # Proactive agent initiation: send initial clientContent to force Coach Alex to speak
            if not self._cold_start_sent:
                logger.info("Sending cold-start trigger...")
                await self._send_cold_start_trigger(fsm_state)
                self._cold_start_sent = True
                logger.info("✓ Cold-start trigger sent")
                
        except Exception as exc:
            logger.error(f"Gemini bridge connection failed: {type(exc).__name__}: {exc}")
            import traceback
            logger.error(traceback.format_exc())
            self._stub = True
            logger.warning("Falling back to stub mode")

    async def _send_cold_start_trigger(self, fsm_state: AppState) -> None:
        """
        Send an initial clientContent turn to trigger Coach Alex's opening line.
        
        This forces the model to speak first without waiting for user input,
        eliminating cold-start silence.
        
        The opening message is in the HOME language to welcome the student,
        then transitions to the target language for the lesson.
        """
        if self._stub or not self.ws:
            logger.warning("Cannot send cold-start trigger - stub mode or no WebSocket")
            return
        
        # Build a warm, welcoming intro in the home language
        home_lang = fsm_state.home_language
        target_lang = fsm_state.target_language
        opening_line = fsm_state.opening_line
        
        if opening_line:
            trigger_text = (
                f"Hello! Welcome to your {target_lang} lesson. I'm Coach Alex, your Socratic language tutor.\n\n"
                f"In this session, we'll practice {target_lang} through a realistic conversation.\n\n"
                f"I'm going to start our roleplay now. I'll speak first, then it'll be your turn to respond.\n\n"
                f"Here we go: {opening_line}"
            )
        else:
            trigger_text = (
                f"Hello! Welcome to your {target_lang} lesson. I'm Coach Alex, your Socratic language tutor.\n\n"
                f"In this session, we'll practice speaking {target_lang} through conversation.\n\n"
                f"I'll start by asking you a question, and then you can respond in {target_lang}. Don't worry about making mistakes - that's how we learn!\n\n"
                f"Let's begin. How are you feeling today?"
            )
        
        cold_start_payload = {
            "clientContent": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": trigger_text}],
                    }
                ],
                "turnComplete": True,
            }
        }
        
        logger.info("→ Sending cold-start clientContent to Gemini:")
        logger.info(f"Trigger text ({len(trigger_text)} chars): {trigger_text[:200]}...")
        logger.info(json.dumps(cold_start_payload, indent=2)[:500] + "...")
        
        try:
            await self.ws.send(json.dumps(cold_start_payload))
            logger.info("✓ Cold-start trigger sent successfully")
        except Exception as exc:
            logger.error(f"Gemini cold-start trigger failed: {type(exc).__name__}: {exc}")

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        if self._stub:
            logger.debug("Stub mode - generating fallback tone")
            self._rx_queue.put_nowait(generate_sine_pcm16(duration_s=0.25))
            return
        if self.ws is None:
            logger.warning("Cannot send audio - WebSocket not connected")
            return
        try:
            await self.ws.send(
                json.dumps(
                    {
                        "realtimeInput": {
                            "mediaChunks": [
                                {
                                    "data": base64.b64encode(pcm_bytes).decode("ascii"),
                                    "mimeType": "audio/pcm;rate=24000",
                                }
                            ]
                        }
                    }
                )
            )
            logger.debug(f"→ Sent audio chunk: {len(pcm_bytes)} bytes")
        except Exception as exc:
            logger.error(f"Gemini send failed: {type(exc).__name__}: {exc}")
            self._stub = True

    async def send_text_prompt(self, text: str) -> None:
        """Send a text user turn to trigger a model audio response."""
        if self._stub:
            logger.debug("Stub mode - generating fallback tone")
            self._rx_queue.put_nowait(generate_sine_pcm16(duration_s=0.25))
            return
        if not self.ws:
            logger.warning("Cannot send text prompt - WebSocket not connected")
            return
        try:
            await self.ws.send(
                json.dumps(
                    {
                        "clientContent": {
                            "turns": [{"role": "user", "parts": [{"text": text}]}],
                            "turnComplete": True,
                        }
                    }
                )
            )
            logger.info(f"→ Sent text prompt: {text[:100]}...")
        except Exception as exc:
            logger.error(f"Gemini text prompt failed: {type(exc).__name__}: {exc}")
            self._stub = True

    async def handle_interrupt(self) -> None:
        # Gemini Live does not expose a dedicated barge-in message. Ending the
        # client turn gracefully encourages the server to finalize its response.
        if self._stub or not self.ws:
            return
        try:
            await self.ws.send(json.dumps({"clientContent": {"turnComplete": True}}))
            logger.info("→ Sent interrupt signal")
        except Exception as exc:
            logger.error(f"Gemini interrupt failed: {type(exc).__name__}: {exc}")

    async def close(self) -> None:
        logger.info("close() called")
        self._closed = True
        self._setup_complete = asyncio.Event()
        self._cold_start_sent = False
        if self._recv_task:
            logger.info("Cancelling receive task...")
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            try:
                await self.ws.close()
                logger.info("✓ WebSocket closed")
            except Exception as exc:
                logger.error(f"Error closing WebSocket: {exc}")
            self.ws = None
        logger.info("✓ Gemini bridge closed")

    async def receive_audio_chunk(self) -> AsyncGenerator[bytes, None]:
        logger.info("receive_audio_chunk() generator started")
        while not self._closed:
            try:
                chunk = await self._rx_queue.get()
                yield chunk
            except asyncio.CancelledError:
                logger.info("receive_audio_chunk() cancelled")
                break

    async def _receive_loop(self) -> None:
        logger.info("=== _receive_loop() started ===")
        message_count = 0
        while not self._closed and self.ws:
            try:
                raw = await self.ws.recv()
                message_count += 1
            except Exception as exc:
                logger.error(f"Receive loop error: {type(exc).__name__}: {exc}")
                break
            if isinstance(raw, bytes):
                # Gemini may occasionally send binary messages; ignore for now.
                logger.debug(f"Received binary message ({message_count}): {len(raw)} bytes - ignoring")
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.error(f"Failed to parse JSON: {exc}")
                continue

            # Signal when setup is complete so we can send cold-start trigger
            if msg.get("setupComplete"):
                logger.info("✓ Received setupComplete from Gemini")
                self._setup_complete.set()
                continue
                
            if "error" in msg:
                logger.error(f"Gemini provider error: {msg.get('error', msg)}")
                continue

            server_content = msg.get("serverContent", {})
            model_turn = server_content.get("modelTurn", {})
            has_audio = False
            for part in model_turn.get("parts", []):
                inline_data = part.get("inlineData", {})
                mime_type = inline_data.get("mimeType", "")
                if mime_type.startswith("audio/"):
                    has_audio = True
                    data = inline_data.get("data", "")
                    if data:
                        try:
                            audio_bytes = base64.b64decode(data)
                            logger.debug(f"← Received audio chunk from Gemini: {len(audio_bytes)} bytes")
                            self._rx_queue.put_nowait(audio_bytes)
                        except Exception as exc:
                            logger.error(f"Failed to decode audio: {exc}")
            
            # Log other message types for debugging (first 20 messages only)
            if not has_audio and message_count < 20:
                logger.debug(f"Received message type: {list(msg.keys())}")
        
        logger.info(f"_receive_loop() exited after {message_count} messages")
