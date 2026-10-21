"""
TypeSafe / Jev System 1 decision wrapper.

This module defines typed schemas for Jev evaluations and an async caller that
performs sub-150 ms evaluations for drift, FSM state choice, and Socratic
compliance scoring. It integrates the canonical DriftCheck and SocraticCheck
models from backend/models/schemas.py and implements the 5-strike penalty
system with lockout and control-frame emission.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

try:
    from backend.models.schemas import (
        DriftCheck,
        SessionStatus,
        SocraticCheck,
        StrikeSeverity,
        UserPreferences,
    )
    from backend.models.database import SessionInstance, StrikeLog
except ImportError:  # pragma: no cover - path fallback
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.models.schemas import (
        DriftCheck,
        SessionStatus,
        SocraticCheck,
        StrikeSeverity,
        UserPreferences,
    )
    from backend.models.database import SessionInstance, StrikeLog

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
    session configuration. Values use the canonical SessionStatus enum.
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


class StrikePenaltyResult(BaseModel):
    """Result of applying a strike and any lockout that results."""

    control_frames: list[dict[str, Any]] = Field(default_factory=list)
    strike_count: int = 0
    is_locked: bool = False
    locked_until: datetime | None = None


class JevGovernor:
    """
    Async wrapper around the TypeSafe / Jev System 1 evaluation service.

    In production this POSTs typed request objects to `TYPESAFE_JEV_ENDPOINT`
    and validates responses. The local implementation performs fast rule-based
    checks that stay within the required 150 ms budget.
    """

    OFF_TOPIC_CONFIDENCE_THRESHOLD: float = 0.80

    # Known jailbreak / prompt-injection markers.
    JAILBREAK_PHRASES: tuple[str, ...] = (
        "ignore previous instructions",
        "ignore your instructions",
        "disregard",
        "you are now",
        "pretend to be",
        "do not follow",
        "bypass",
        "jailbreak",
        "system prompt",
        "developer mode",
        "DAN",
        "root mode",
        "you have been",
        "new instructions",
    )

    # Generic off-topic markers for a language-learning context.
    OFF_TOPIC_TRIGGERS: tuple[str, ...] = (
        "what is the capital of",
        "weather",
        "who is the president",
        "solve this math problem",
        "write a poem",
        "tell me a joke",
        "quantum physics",
        "meaning of life",
        "explain quantum",
        "stock price",
        "crypto",
        "bitcoin",
    )

    # Imperative / directive markers that violate Socratic, question-led style.
    DIRECTIVE_PHRASES: tuple[str, ...] = (
        "you should",
        "the answer is",
        "correct answer",
        "wrong",
        "you must",
        "you always",
        "you never",
        "you need to",
        "you have to",
        "just say",
        "say this",
        "remember that",
    )

    IMPERATIVE_STARTS: tuple[str, ...] = (
        "say",
        "use",
        "tell",
        "give",
        "write",
        "explain",
        "describe",
        "name",
        "list",
        "choose",
        "pick",
        "repeat",
        "practice",
    )

    def __init__(self, api_key: str | None = None, endpoint: str | None = None) -> None:
        self.api_key = api_key or os.getenv("TYPESAFE_JEV_API_KEY", "")
        self.endpoint = endpoint or os.getenv("TYPESAFE_JEV_ENDPOINT", "")

    # ------------------------------------------------------------------
    # Drift / Noul check
    # ------------------------------------------------------------------

    def evaluate_drift(self, transcript: str, fsm: FSMManager) -> DriftCheck:
        """Return a DriftCheck for the user's utterance."""
        if not isinstance(transcript, str):
            raise TypeError("transcript must be a string")

        lowered = transcript.lower()
        target_match = [
            w for w in fsm.vocabulary if w.lower() in lowered
        ]
        scenario_topic = (fsm.scenario.get("topic") or "").lower()
        word_count = len([w for w in lowered.split() if w.strip()])

        detected_jailbreak = any(phrase in lowered for phrase in self.JAILBREAK_PHRASES)
        off_topic_trigger = any(phrase in lowered for phrase in self.OFF_TOPIC_TRIGGERS)

        is_off_topic = False
        drift_type: Optional[str] = None

        if detected_jailbreak:
            is_off_topic = True
            drift_type = "jailbreak"
        elif off_topic_trigger and not target_match:
            is_off_topic = True
            drift_type = "off_topic"
        elif (
            scenario_topic
            and scenario_topic not in lowered
            and not target_match
            and word_count > 2
        ):
            is_off_topic = True
            drift_type = "off_topic"

        if detected_jailbreak:
            confidence = 0.95
        elif is_off_topic:
            confidence = 0.85
        elif not target_match and word_count > 2:
            confidence = 0.5
        else:
            confidence = round(random.uniform(0.0, 0.15), 3)

        if drift_type is None and not target_match and word_count > 2:
            drift_type = "low_match"

        reasoning = (
            "Detected jailbreak-like prompt injection."
            if detected_jailbreak
            else "Detected off-topic input."
            if is_off_topic
            else "Input aligns with lesson scope."
        )

        return DriftCheck(
            is_off_topic=is_off_topic,
            confidence=confidence,
            detected_jailbreak=detected_jailbreak,
            drift_type=drift_type,
            context=transcript,
            current_text=transcript,
        )

    async def check_drift(self, transcript: str, fsm: FSMManager) -> NoulResult:
        """Run the Noul drift / entity check (legacy wrapper)."""
        await self._simulate_latency()
        drift = self.evaluate_drift(transcript, fsm)
        return NoulResult(
            drift_detected=drift.is_off_topic or drift.detected_jailbreak,
            is_off_topic=drift.is_off_topic,
            target_match=[
                w for w in fsm.vocabulary if w.lower() in transcript.lower()
            ],
            confidence=drift.confidence,
            reasoning=drift.drift_type or "input aligns with lesson scope",
        )

    # ------------------------------------------------------------------
    # Socratic / Score check
    # ------------------------------------------------------------------

    def evaluate_socratic(self, tutor_text: str) -> SocraticCheck:
        """Return a SocraticCheck for the AI/tutor response."""
        if not isinstance(tutor_text, str):
            raise TypeError("tutor_text must be a string")

        text = tutor_text.strip()
        if not text:
            return SocraticCheck(
                is_question_led=False,
                directive_ratio=0.0,
                recommended_interrupt=False,
                context=tutor_text,
                current_text=text,
            )

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        total = len(sentences)
        questions = sum(1 for s in sentences if s.endswith("?"))
        directives = 0

        for s in sentences:
            lower = s.lower()
            if any(phrase in lower for phrase in self.DIRECTIVE_PHRASES):
                directives += 1
                continue
            first_word = re.sub(r"[^a-z]", "", lower.split()[0]) if lower.split() else ""
            if first_word in self.IMPERATIVE_STARTS:
                directives += 1

        question_ratio = questions / total if total else 0.0
        directive_ratio = directives / total if total else 0.0

        first_sentence = sentences[0]
        is_question_led = first_sentence.endswith("?") and question_ratio >= 0.5
        recommended_interrupt = (
            not is_question_led
            and (directive_ratio > 0.5 or question_ratio < 0.3)
            and total >= 1
        )

        return SocraticCheck(
            is_question_led=is_question_led,
            directive_ratio=round(directive_ratio, 3),
            recommended_interrupt=recommended_interrupt,
            context=tutor_text,
            current_text=text,
        )

    async def score_tutor_response(self, tutor_text: str) -> ScoreResult:
        """Run the Score Socratic compliance evaluation (legacy wrapper)."""
        await self._simulate_latency()
        socratic = self.evaluate_socratic(tutor_text)
        return ScoreResult(
            socratic_score=0.85 if socratic.is_question_led else 0.25,
            directive_detected=socratic.directive_ratio > 0.5,
            interrupt_recommended=socratic.recommended_interrupt,
            reasoning=(
                "Directive statement detected; recommend interrupt."
                if socratic.recommended_interrupt
                else "Response is Socratic and question-led."
            ),
        )

    # ------------------------------------------------------------------
    # Choice / FSM state decision
    # ------------------------------------------------------------------

    async def choose_state(self, fsm: FSMManager, transcript: str) -> ChoiceResult:
        """Run the Choice FSM state decision."""
        await self._simulate_latency()

        current = fsm.phase
        used_count = len(fsm.context_summary.get("used_vocabulary", []))

        # Simple heuristic progression.
        if current == SessionStatus.WARMUP and used_count >= 1:
            return ChoiceResult(
                next_state="DRILL",
                transition_reason="student_used_target_vocabulary",
                required_vocabulary=fsm.vocabulary[:2],
            )
        if current == SessionStatus.DRILL and used_count >= 3:
            return ChoiceResult(
                next_state="ROLEPLAY",
                transition_reason="student_ready_for_open_scenario",
                required_vocabulary=fsm.vocabulary,
            )
        if current == SessionStatus.ROLEPLAY and used_count >= len(fsm.vocabulary):
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

    # ------------------------------------------------------------------
    # Combined evaluation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 5-strike penalty system with lockout
    # ------------------------------------------------------------------

    @staticmethod
    def classify_severity(drift: DriftCheck) -> StrikeSeverity:
        """Map a DriftCheck to a StrikeSeverity."""
        if drift.detected_jailbreak:
            return StrikeSeverity.CRITICAL
        if drift.is_off_topic and drift.confidence >= 0.80:
            return StrikeSeverity.MAJOR
        if drift.is_off_topic:
            return StrikeSeverity.MINOR
        return StrikeSeverity.MINOR

    @staticmethod
    def _new_strike_id() -> str:
        return f"strike_{uuid.uuid4().hex}"

    def record_strike(
        self,
        session: SessionInstance,
        severity: StrikeSeverity,
        drift_type: Optional[str],
        context: str,
        db_session: Any | None = None,
    ) -> StrikeLog | dict[str, Any]:
        """
        Persist a strike log entry, increment the session strike counter, and
        return the created strike record.

        If db_session is provided, the StrikeLog ORM instance is added to it but
        not committed here (the caller owns the transaction boundary).
        """
        if session is None:
            raise ValueError("session is required")
        if not isinstance(severity, StrikeSeverity):
            raise TypeError("severity must be a StrikeSeverity enum value")

        session.strike_count += 1

        strike_data = {
            "strike_id": self._new_strike_id(),
            "user_id": session.user_id,
            "session_id": session.session_id,
            "severity": severity,
            "drift_type": drift_type,
            "context": context,
        }

        if db_session is not None:
            orm_strike = StrikeLog(**strike_data)
            db_session.add(orm_strike)
            return orm_strike

        return strike_data

    def apply_strike_penalty(
        self,
        session: SessionInstance,
        preferences: UserPreferences | None = None,
        db_session: Any | None = None,
    ) -> list[dict[str, Any]]:
        """
        Apply the 5-strike penalty system.

        Emits a STRIKE_WARNING control frame after every strike and a
        LOCKOUT_SIGNAL when the strike count reaches the configured maximum.
        The session is moved to SessionStatus.PAUSE on lockout.
        """
        if session is None:
            raise ValueError("session is required")

        max_strikes = getattr(preferences, "max_strikes", 5) if preferences else 5
        lockout_ms = (
            getattr(preferences, "strike_lockout_duration_ms", 3600000)
            if preferences
            else 3600000
        )

        control_frames: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        if session.strike_count >= max_strikes:
            locked_until = now + timedelta(milliseconds=lockout_ms)
            session.is_locked = True
            session.locked_until = locked_until
            session.status = SessionStatus.PAUSE

            control_frames.append(
                {
                    "type": "LOCKOUT_SIGNAL",
                    "source": "jev_penalty",
                    "reason": "max_strikes_reached",
                    "target_state": SessionStatus.PAUSE.value,
                    "payload": {
                        "strike_count": session.strike_count,
                        "max_strikes": max_strikes,
                        "locked_until": locked_until.isoformat(),
                        "lockout_duration_ms": lockout_ms,
                    },
                }
            )
        else:
            control_frames.append(
                {
                    "type": "STRIKE_WARNING",
                    "source": "jev_penalty",
                    "reason": "strike_recorded",
                    "target_state": session.status.value,
                    "payload": {
                        "strike_count": session.strike_count,
                        "max_strikes": max_strikes,
                        "remaining_strikes": max_strikes - session.strike_count,
                    },
                }
            )

        if db_session is not None:
            db_session.add(session)

        return control_frames

    def process_turn(
        self,
        transcript: str,
        tutor_text: str,
        fsm: FSMManager,
        session: SessionInstance | None = None,
        preferences: UserPreferences | None = None,
        db_session: Any | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate one full user/tutor turn, record any strikes, and return all
        control frames produced.

        If a strike is recorded, the strike and lockout logic are applied before
        returning. The caller is responsible for committing db_session.
        """
        if not isinstance(transcript, str):
            raise TypeError("transcript must be a string")
        if not isinstance(tutor_text, str):
            raise TypeError("tutor_text must be a string")

        drift = self.evaluate_drift(transcript, fsm)
        socratic = self.evaluate_socratic(tutor_text)
        control_frames: list[dict[str, Any]] = []

        # Only penalize high-confidence off-topic / jailbreak drift.
        if (
            (drift.is_off_topic or drift.detected_jailbreak)
            and drift.confidence >= self.OFF_TOPIC_CONFIDENCE_THRESHOLD
            and session is not None
        ):
            severity = self.classify_severity(drift)
            self.record_strike(
                session=session,
                severity=severity,
                drift_type=drift.drift_type,
                context=transcript,
                db_session=db_session,
            )
            penalty_frames = self.apply_strike_penalty(session, preferences, db_session)
            control_frames.extend(penalty_frames)

        # Socratic interrupt recommendation is emitted as a non-strike frame.
        if socratic.recommended_interrupt:
            control_frames.append(
                {
                    "type": "INTERRUPT_SIGNAL",
                    "source": "jev_socratic",
                    "reason": "response_not_question_led",
                    "payload": {
                        "directive_ratio": socratic.directive_ratio,
                        "is_question_led": socratic.is_question_led,
                    },
                }
            )

        return {
            "drift": drift.model_dump(),
            "socratic": socratic.model_dump(),
            "control_frames": control_frames,
        }

    async def _simulate_latency(self) -> None:
        """Simulate a sub-150 ms network round-trip to the Jev service."""
        await asyncio.sleep(random.uniform(0.010, 0.120))
