"""Stub audio bridge that always returns the synthetic dev tone."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from .base import AppState, BaseAudioBridge, generate_sine_pcm16


class StubAudioBridge(BaseAudioBridge):
    """Always-local fallback bridge used when AUDIO_PROVIDER=stub."""

    PROVIDER = "stub"

    def __init__(self) -> None:
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    async def connect(self, fsm_state: AppState) -> None:
        return

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        self._rx_queue.put_nowait(generate_sine_pcm16(duration_s=0.25))

    async def send_text_prompt(self, text: str) -> None:
        """Stub prompt response: emit a short synthetic tone."""
        self._rx_queue.put_nowait(generate_sine_pcm16(duration_s=0.25))

    async def receive_audio_chunk(self) -> AsyncGenerator[bytes, None]:
        while not self._closed:
            try:
                chunk = await self._rx_queue.get()
            except asyncio.CancelledError:
                break
            yield chunk

    async def handle_interrupt(self) -> None:
        return

    async def close(self) -> None:
        self._closed = True
