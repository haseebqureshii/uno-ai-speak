"""
TypeSafe / Jev System 1 decision wrapper.

This module defines typed schemas for Jev evaluations and an async caller that
simulates sub-150 ms evaluations for drift, FSM state choice, and Socratic
compliance scoring. It also provides the Noul "is_off_topic" check used by the
5-strikes penalty system.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Literal

from pydantic import BaseModel, Field

from fsm import FSMManager


class NoulResult(BaseModel):
    """
    Drift / entity check.

    `is_off_topic` is the primary signal for the 5-strikes penalty. When
    `drift_detected` is True and `confidence` exceeds the configured threshold,
    the backend increments the session's strike counter.
    """

    drift_detected: bool
    is_off_topic: bool = False
    target_match: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reasoning: str = ""


class ChoiceResult(BaseModel):
    """
    FSM state decision.

    Selects the next lesson phase given the current phase, transcript, and
    session configuration.
    """

    next_state: Literal["WARMUP", "DRILL", "ROLEPLAY", "PAUSE", "WRAPUP"]
    transition_reason: str = ""
    required_vocabulary: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    """
    Socratic compliance score.

    Measures whether the tutor's last response followed Socratic norms
    (question-led, non-directive, scaffolded).
    """

    socratic_score: float = Field(ge=0.0, le=1.0)
    directive_detected: bool
    interrupt_recommended: bool
    reasoning: str = ""


class JevGovernor:
    """
    Async wrapper around the TypeSafe / Jev System 1 evaluation service.

    In production this POSTs typed request objects to `TYPESAFE_JEV_ENDPOINT`
    and validates responses. The stub returns deterministic-ish mock values
    within the required 150 ms budget.
    """

    OFF_TOPIC_CONFIDENCE_THRESHOLD: float = 0.80

    def __init__(self, api_key: str | None = None, endpoint: str | None = None) -> None:
        self.api_key = api_key or os.getenv("TYPESAFE_JEV_API_KEY", "")
        self.endpoint = endpoint or os.getenv("TYPESAFE_JEV_ENDPOINT", "")

    async def check_drift(self, transcript: str, fsm: FSMManager) -> NoulResult:
        """Run the Noul drift / entity check, including the is_off_topic signal."""
        await self._simulate_latency()

        lowered = transcript.lower()
        matches = [w for w in fsm.vocabulary if w.lower() in lowered]

        # Mock jailbreak / off-topic detection.
        off_topic_phrases = [
            "ignore previous instructions",
            "what is the capital of",
            "write a poem",
            "solve this math problem",
            "who is the president",
            "tell me a joke",
            "you are now",
            "pretend to be",
        ]
        is_off_topic = any(phrase in lowered for phrase in off_topic_phrases)
        drift = not bool(matches) and len(transcript.split()) > 2

        # For the stub, force a high-confidence off-topic signal when a
        # jailbreak phrase is present so the 5-strikes path can be exercised.
        confidence = (
            round(random.uniform(0.82, 0.97), 3)
            if is_off_topic
            else (round(random.uniform(0.15, 0.45), 3) if drift else round(random.uniform(0.0, 0.15), 3))
        )

        return NoulResult(
            drift_detected=drift or is_off_topic,
            is_off_topic=is_off_topic,
            target_match=matches,
            confidence=confidence,
            reasoning=(
                "Detected off-topic / jailbreak-like input."
                if is_off_topic
                else "Input does not match target vocabulary."
                if drift
                else "Input aligns with lesson scope."
            ),
        )

    async def choose_state(self, fsm: FSMManager, transcript: str) -> ChoiceResult:
        """Run the Choice FSM state decision."""
        await self._simulate_latency()

        current = fsm.phase
        used_count = len(fsm.context_summary.get("used_vocabulary", []))

        # Simple heuristic progression for the stub.
        if current.value == "WARMUP" and used_count >= 1:
            return ChoiceResult(
                next_state="DRILL",
                transition_reason="student_used_target_vocabulary",
                required_vocabulary=fsm.vocabulary[:2],
            )
        if current.value == "DRILL" and used_count >= 3:
            return ChoiceResult(
                next_state="ROLEPLAY",
                transition_reason="student_ready_for_open_scenario",
                required_vocabulary=fsm.vocabulary,
            )
        if current.value == "ROLEPLAY" and used_count >= len(fsm.vocabulary):
            return ChoiceResult(
                next_state="WRAPUP",
                transition_reason="all_vocabulary_used",
                required_vocabulary=[],
            )

        return ChoiceResult(
            next_state=current.value,
            transition_reason="no_state_change_needed",
            required_vocabulary=fsm.vocabulary,
        )

    async def score_tutor_response(self, tutor_text: str) -> ScoreResult:
        """Run the Score Socratic compliance evaluation."""
        await self._simulate_latency()

        lowered = tutor_text.lower()
        directive_keywords = ("you should", "the answer is", "correct answer", "wrong")
        directive = any(kw in lowered for kw in directive_keywords)
        score = 0.25 if directive else round(random.uniform(0.75, 0.98), 3)

        return ScoreResult(
            socratic_score=score,
            directive_detected=directive,
            interrupt_recommended=directive,
            reasoning=(
                "Directive statement detected; recommend interrupt."
                if directive
                else "Response is Socratic and question-led."
            ),
        )

    async def evaluate_all(
        self,
        transcript: str,
        tutor_text: str,
        fsm: FSMManager,
    ) -> dict[str, Any]:
        """Convenience method to run all three evaluations concurrently."""
        noul, choice, score = await asyncio.gather(
            self.check_drift(transcript, fsm),
            self.choose_state(fsm, transcript),
            self.score_tutor_response(tutor_text),
        )
        return {
            "noul": noul.model_dump(),
            "choice": choice.model_dump(),
            "score": score.model_dump(),
        }

    async def _simulate_latency(self) -> None:
        """Simulate a sub-150 ms network round-trip to the Jev service."""
        await asyncio.sleep(random.uniform(0.010, 0.120))
