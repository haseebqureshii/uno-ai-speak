"""Provider-agnostic audio bridge package."""

from .base import AppState, BaseAudioBridge
from .factory import get_audio_bridge

__all__ = ["AppState", "BaseAudioBridge", "get_audio_bridge"]
