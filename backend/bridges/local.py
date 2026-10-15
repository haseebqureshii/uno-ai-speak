"""Local / self-hosted OpenAI-Realtime-compatible audio bridge."""

from __future__ import annotations

import os

from .openai import OpenAIAudioBridge


class LocalAudioBridge(OpenAIAudioBridge):
    """
    Bridge to a local OpenAI-Realtime-compatible endpoint.

    Defaults to ``ws://localhost:8080/v1/realtime``, which matches LocalAI,
    Ollama + Whisper + Kokoro/Piper TTS cascaded wrappers, and other self-hosted
    realtime servers. If the local server is not reachable, it falls back to the
    synthetic dev tone generator inherited from ``OpenAIAudioBridge`` stub mode,
    so the app works with zero external API keys or cost.
    """

    PROVIDER = "local"

    def __init__(self) -> None:
        super().__init__(
            api_key=os.getenv("LOCAL_AUDIO_API_KEY", "dummy"),
            base_url=os.getenv("LOCAL_AUDIO_URL", "ws://localhost:8080/v1/realtime"),
            model=os.getenv("LOCAL_AUDIO_MODEL", "local"),
            voice=os.getenv("LOCAL_AUDIO_VOICE", "alloy"),
        )
