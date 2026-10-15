"""Abstract audio bridge interface and shared helpers."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, List


@dataclass
class AppState:
    """Lightweight snapshot of lesson state passed to a bridge at connect time."""

    session_id: str
    client_id: str
    target_language: str
    home_language: str
    proficiency_level: str
    session_length_minutes: int
    lockout_cooldown_minutes: int
    vocabulary: List[str]
    system_prompt: str
    scenario_id: str = ""
    ai_role: str = ""
    user_task: str = ""
    target_lexicon: List[str] = None  # type: ignore[assignment]
    opening_line: str = ""
    completion_conditions: List[str] = None  # type: ignore[assignment]
    weak_lexicon: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.target_lexicon is None:
            self.target_lexicon = []
        if self.completion_conditions is None:
            self.completion_conditions = []
        if self.weak_lexicon is None:
            self.weak_lexicon = []


def generate_sine_pcm16(
    duration_s: float = 0.25,
    sample_rate: int = 24000,
    frequency: float = 440.0,
    amplitude: float = 0.3,
) -> bytes:
    """Generate a short PCM16 little-endian mono fallback tone for local dev."""
    samples = int(duration_s * sample_rate)
    data = bytearray()
    for i in range(samples):
        value = int(
            32767 * amplitude * math.sin(2.0 * math.pi * frequency * (i / sample_rate))
        )
        data.extend(value.to_bytes(2, "little", signed=True))
    return bytes(data)


class BaseAudioBridge(ABC):
    """Provider-agnostic audio bridge for full-duplex speech I/O."""

    @abstractmethod
    async def connect(self, fsm_state: AppState) -> None:
        """Establish connection and perform provider-specific setup."""
        ...

    @abstractmethod
    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """Send one raw PCM16 24kHz mono chunk to the provider."""
        ...

    @abstractmethod
    async def send_text_prompt(self, text: str) -> None:
        """Send a text user turn to trigger a model audio response."""
        ...

    @abstractmethod
    async def receive_audio_chunk(self) -> AsyncGenerator[bytes, None]:
        """Yield raw PCM16 24kHz mono chunks from the provider."""
        yield b""

    @abstractmethod
    async def handle_interrupt(self) -> None:
        """Signal an interruption / barge-in event to the provider."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release all resources."""
        ...
