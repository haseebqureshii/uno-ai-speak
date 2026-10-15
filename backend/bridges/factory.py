"""Audio bridge factory."""

from __future__ import annotations

import os

from .base import BaseAudioBridge
from .gemini import GeminiAudioBridge
from .local import LocalAudioBridge
from .openai import OpenAIAudioBridge
from .stub import StubAudioBridge

_VALID_PROVIDERS = {"local", "openai", "gemini", "stub"}


def get_audio_bridge(provider: str | None = None) -> BaseAudioBridge:
    """
    Return an audio bridge instance for the requested provider.

    Resolution order:
      1. ``provider`` argument if provided and valid.
      2. ``AUDIO_PROVIDER`` environment variable if set and valid.
      3. ``GeminiAudioBridge`` (live audio default).
    """
    chosen = (provider or os.getenv("AUDIO_PROVIDER", "gemini")).lower().strip()
    if chosen not in _VALID_PROVIDERS:
        chosen = "gemini"

    if chosen == "openai":
        return OpenAIAudioBridge()
    if chosen == "gemini":
        return GeminiAudioBridge()
    if chosen == "stub":
        return StubAudioBridge()
    return LocalAudioBridge()
