"""OpenAI Realtime API audio bridge."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, AsyncGenerator

from .base import AppState, BaseAudioBridge, generate_sine_pcm16

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]


class OpenAIAudioBridge(BaseAudioBridge):
    """Bridge to the OpenAI Realtime API (gpt-4o-realtime-preview)."""

    PROVIDER = "openai"
    DEFAULT_MODEL = "gpt-4o-realtime-preview-2024-12-17"
    DEFAULT_VOICE = "alloy"
    SAMPLE_RATE = 24000

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        voice: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or "wss://api.openai.com/v1/realtime"
        self.model = model or self.DEFAULT_MODEL
        self.voice = voice or self.DEFAULT_VOICE
        self.ws: Any = None
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
        self._closed = False
        self._stub = not (self.api_key and self.api_key.strip())

    async def connect(self, fsm_state: AppState) -> None:
        if self._stub:
            return
        if websockets is None:
            raise RuntimeError("websockets package is required for the OpenAI audio bridge")

        uri = f"{self.base_url}?model={self.model}"
        try:
            self.ws = await websockets.connect(
                uri,
                additional_headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
            )
            await self.ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": ["audio", "text"],
                            "instructions": fsm_state.system_prompt,
                            "voice": self.voice,
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm16",
                            "input_audio_transcription": {"model": "whisper-1"},
                            "turn_detection": {"type": "server_vad"},
                        },
                    }
                )
            )
            self._recv_task = asyncio.create_task(self._receive_loop())
        except Exception as exc:
            self._stub = True
            print(f"OpenAI bridge connection failed, falling back to stub: {exc}")

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        if self._stub:
            self._rx_queue.put_nowait(generate_sine_pcm16(duration_s=0.25))
            return
        if self.ws is None:
            return
        try:
            await self.ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm_bytes).decode("ascii"),
                    }
                )
            )
        except Exception as exc:
            print(f"OpenAI send failed: {exc}")
            self._stub = True

    async def send_text_prompt(self, text: str) -> None:
        """Send a text user item and request a model audio response."""
        if self._stub:
            self._rx_queue.put_nowait(generate_sine_pcm16(duration_s=0.25))
            return
        if not self.ws:
            return
        try:
            await self.ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }
                )
            )
            await self.ws.send(json.dumps({"type": "response.create"}))
        except Exception as exc:
            print(f"OpenAI text prompt failed: {exc}")
            self._stub = True

    async def handle_interrupt(self) -> None:
        if self._stub or not self.ws:
            return
        try:
            await self.ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
            await self.ws.send(json.dumps({"type": "response.cancel"}))
        except Exception as exc:
            print(f"OpenAI interrupt failed: {exc}")

    async def close(self) -> None:
        self._closed = True
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    async def receive_audio_chunk(self) -> AsyncGenerator[bytes, None]:
        while not self._closed:
            try:
                chunk = await self._rx_queue.get()
            except asyncio.CancelledError:
                break
            yield chunk

    async def _receive_loop(self) -> None:
        while not self._closed and self.ws:
            try:
                raw = await self.ws.recv()
            except Exception:
                break
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "response.audio.delta":
                chunk_b64 = msg.get("audio", "")
                if chunk_b64:
                    try:
                        self._rx_queue.put_nowait(base64.b64decode(chunk_b64))
                    except Exception:
                        pass
            elif msg_type == "error":
                print(f"OpenAI provider error: {msg.get('error', msg)}")
