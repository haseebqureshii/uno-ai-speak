"""
Finite State Machine manager for lesson phases.

Uses the canonical SessionStatus enum from backend/models/schemas.py.
Maintains the 5-state flow: WARMUP → DRILL → ROLEPLAY → WRAPUP → PAUSE,
with optional pause/resume support and a lightweight strike/lockout state.
"""

from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from backend.models.schemas import SessionStatus, StrikeSeverity
except ImportError:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.models.schemas import SessionStatus, StrikeSeverity


# Backward-compatible alias for callers that import LessonPhase.
LessonPhase = SessionStatus


VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.WARMUP: {SessionStatus.DRILL, SessionStatus.PAUSE},
    SessionStatus.DRILL: {SessionStatus.ROLEPLAY, SessionStatus.PAUSE},
    SessionStatus.ROLEPLAY: {SessionStatus.WRAPUP, SessionStatus.PAUSE},
    SessionStatus.WRAPUP: {SessionStatus.PAUSE},
    SessionStatus.PAUSE: {
        SessionStatus.WARMUP,
        SessionStatus.DRILL,
        SessionStatus.ROLEPLAY,
        SessionStatus.WRAPUP,
    },
}


# Fixed, non-customizable Socratic Tutor persona.
COACH_ALEX_PERSONA = """You are Coach Alex, an encouraging but highly disciplined,
audio-first Socratic language tutor. Your job is to help the student practice
speaking {target_language} through questions, scaffolding, and roleplay. You never
give long explanations. You never break character. You keep every response short,
vocal, and interactive."""


SCENARIOS_PATH = Path(__file__).parent / "data" / "scenarios.json"


def _load_scenarios() -> list[dict[str, Any]]:
    """Load the scenario manifest, returning an empty list if it is missing."""
    if not SCENARIOS_PATH.exists():
        return []
    try:
        with SCENARIOS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("scenarios", [])
    except Exception:
        return []


class TransitionError(ValueError):
    """Raised when a requested state transition is disallowed."""

    def __init__(self, current: SessionStatus, target: SessionStatus, reason: str = "") -> None:
        self.current = current
        self.target = target
        msg = f"Invalid transition from {current.value} to {target.value}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class FSMManager:
    """
    Tracks the current lesson phase, active session configuration, vocabulary
    targets, strike/lockout state, a rolling text summary, and the selected TBLT
    scenario.

    Invariants:
    - Exactly one target language is active per session.
    - Coach Alex persona is fixed and non-customizable.
    - L1 Safety Valve is applied only for A1/A2 proficiency levels.
    - Session state uses the canonical SessionStatus enum.
    """

    def __init__(
        self,
        session_id: str,
        client_id: str,
        target_language: str,
        home_language: str,
        proficiency_level: str,
        session_length_minutes: int,
        lockout_cooldown_minutes: int = 15,
        vocabulary: list[str] | None = None,
        weak_lexicon: list[str] | None = None,
    ) -> None:
        if not session_id or not isinstance(session_id, str):
            raise ValueError("session_id must be a non-empty string")
        if not client_id or not isinstance(client_id, str):
            raise ValueError("client_id must be a non-empty string")
        if not target_language:
            raise ValueError("target_language is required and must be a single language")
        if proficiency_level not in {"A1", "A2", "B1", "B2", "C1"}:
            raise ValueError("proficiency_level must be one of A1, A2, B1, B2, C1")
        if not (5 <= lockout_cooldown_minutes <= 60):
            raise ValueError("lockout_cooldown_minutes must be between 5 and 60")

        self.session_id = session_id
        self.client_id = client_id
        self.target_language = target_language
        self.home_language = home_language
        self.proficiency_level = proficiency_level
        self.session_length_minutes = session_length_minutes
        self.lockout_cooldown_minutes = lockout_cooldown_minutes
        self.weak_lexicon = list(weak_lexicon or [])

        self.scenario: dict[str, Any] = self._select_scenario()
        self.vocabulary: list[str] = vocabulary or self._default_vocabulary()

        self.phase = SessionStatus.WARMUP
        self.drift_strikes = 0
        self.is_locked_out = False
        self.lockout_until: datetime | None = None

        self.context_summary: dict[str, Any] = {
            "language": target_language,
            "home_language": home_language,
            "proficiency_level": proficiency_level,
            "scenario_id": self.scenario.get("id", ""),
            "started_vocabulary": list(self.vocabulary),
            "used_vocabulary": [],
            "mistakes": [],
            "milestones": [],
            "drift_strikes": 0,
        }
        self.last_tutor_text: str = ""
        self._pause_stack: list[SessionStatus] = []

        # Simple spoken transcript (text when available, byte markers otherwise).
        self.transcript: list[dict[str, Any]] = []

    def record_user_audio_frame(self, byte_count: int) -> None:
        """Record raw audio activity, coalescing rapid chunks into one user turn."""
        marker = f"[audio:{byte_count} bytes]"
        if self.transcript and self.transcript[-1]["role"] == "user":
            last = self.transcript[-1]["text"]
            if last.startswith("[audio:"):
                # Update the cumulative byte marker rather than creating a new turn.
                self.transcript[-1]["text"] = f"[audio:+{byte_count} bytes]"
                return
        self.transcript.append(
            {
                "role": "user",
                "text": marker,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _select_scenario(self) -> dict[str, Any]:
        """Pick a scenario matching the target language and CEFR level."""
        scenarios = _load_scenarios()
        if not scenarios:
            return {}

        target_lang = self.target_language.strip().lower()
        level = self.proficiency_level

        matches = [
            s
            for s in scenarios
            if s.get("cefr_level") == level
            and s.get("language", "").strip().lower() == target_lang
        ]

        # If no exact language match, fall back to any scenario at this level.
        if not matches:
            matches = [s for s in scenarios if s.get("cefr_level") == level]

        # Prefer a scenario that naturally exercises weak vocabulary.
        if self.weak_lexicon:
            target_words = {w.lower() for w in self.weak_lexicon}
            weighted = []
            for s in matches:
                lexicon = {t.lower() for t in s.get("target_lexicon", [])}
                overlap = len(target_words & lexicon)
                weighted.append((overlap, s))
            weighted.sort(key=lambda x: x[0], reverse=True)
            if weighted and weighted[0][0] > 0:
                return weighted[0][1]

        return random.choice(matches) if matches else scenarios[0]

    def _default_vocabulary(self) -> list[str]:
        """Language-aware placeholder vocabulary for when no scenario is selected."""
        if self.scenario:
            return list(self.scenario.get("target_lexicon", []))
        lang = self.target_language.lower()
        if "spanish" in lang or "español" in lang:
            return ["hola", "cómo estás", "bien", "gracias", "adiós"]
        if "french" in lang or "français" in lang:
            return ["bonjour", "comment allez-vous", "bien", "merci", "au revoir"]
        if "german" in lang or "deutsch" in lang:
            return ["hallo", "wie geht's", "gut", "danke", "tschüss"]
        return ["hello", "how are you", "good", "thank you", "goodbye"]

    def can_transition_to(self, next_state: str | SessionStatus) -> bool:
        """Return True if the requested state transition is allowed."""
        target = next_state if isinstance(next_state, SessionStatus) else SessionStatus(next_state)
        if self.phase == target:
            return True
        return target in VALID_TRANSITIONS.get(self.phase, set())

    def transition(self, next_state: str, reason: str) -> SessionStatus:
        """
        Attempt a state transition.

        Raises:
            TransitionError: if the requested transition is not allowed.
        """
        target = SessionStatus(next_state)
        if not self.can_transition_to(target):
            raise TransitionError(self.phase, target, reason)

        if target == SessionStatus.PAUSE:
            self._pause_stack.append(self.phase)

        previous = self.phase
        self.phase = target
        self._record_milestone(f"transition:{previous.value}->{target.value}", reason)
        return self.phase

    def resume_from_pause(self) -> SessionStatus:
        """Resume from PAUSE to the phase stored on the pause stack."""
        if not self._pause_stack:
            raise ValueError("No paused phase to resume to")
        previous_pause = self._pause_stack.pop()
        self.phase = previous_pause
        self._record_milestone("resume", f"restored_phase:{self.phase.value}")
        return self.phase

    def record_user_turn(self, text: str) -> None:
        """Store a user turn in the rolling transcript."""
        self.transcript.append(
            {
                "role": "user",
                "text": text,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        # Track any target vocabulary used in this turn.
        for word in self.scenario.get("target_lexicon", []):
            if self._contains_word(text, word):
                self.record_vocabulary_used(word)

    def record_tutor_turn(self, text: str) -> None:
        """Store a tutor turn in the rolling transcript."""
        self.transcript.append(
            {
                "role": "assistant",
                "text": text,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _contains_word(text: str, word: str) -> bool:
        """Case-insensitive, punctuation-insensitive substring check."""
        clean = re.sub(r"[^\w\s]", "", text.lower())
        return word.lower() in clean

    def record_vocabulary_used(self, word: str) -> None:
        """Track a vocabulary item the student successfully used."""
        used = self.context_summary["used_vocabulary"]
        if word not in used:
            used.append(word)

    def record_mistake(self, mistake: str, correction: str) -> None:
        """Track a mistake and its correction in the rolling summary."""
        self.context_summary["mistakes"].append(
            {"mistake": mistake, "correction": correction}
        )

    def set_last_tutor_text(self, text: str) -> None:
        """Store the most recent tutor text for Socratic compliance scoring."""
        self.last_tutor_text = text

    def increment_strike(self) -> int:
        """Increment the drift strike counter and return the new count."""
        self.drift_strikes += 1
        self.context_summary["drift_strikes"] = self.drift_strikes
        self._record_milestone("strike_incremented", f"strike_count:{self.drift_strikes}")
        return self.drift_strikes

    def apply_lockout(self) -> datetime:
        """Lock the session out for the configured cooldown duration."""
        self.is_locked_out = True
        self.lockout_until = datetime.now(timezone.utc) + timedelta(
            minutes=self.lockout_cooldown_minutes
        )
        self._record_milestone(
            "lockout_applied",
            f"until:{self.lockout_until.isoformat()}",
        )
        return self.lockout_until

    def is_lockout_active(self) -> bool:
        """Return True if the session is currently locked out."""
        if not self.is_locked_out or self.lockout_until is None:
            return False
        if datetime.now(timezone.utc) >= self.lockout_until:
            self.clear_lockout()
            return False
        return True

    def clear_lockout(self) -> None:
        """Clear an expired lockout."""
        self.is_locked_out = False
        self.lockout_until = None
        self.drift_strikes = 0
        self.context_summary["drift_strikes"] = 0

    def flush_audio_context(self) -> dict[str, Any]:
        """
        Called every 3 minutes to drop raw audio KV caches while keeping text state.

        Returns:
            The persisted context summary.
        """
        self._record_milestone("audio_flush", "dropped_audio_kv_cache")
        return self.context_summary

    def build_system_prompt(self, student_message: str = "") -> str:
        """
        Build the fixed Coach Alex system prompt, including the selected scenario,
        weak-vocabulary priming, and the L1 Safety Valve rule for A1/A2 learners.
        """
        base = COACH_ALEX_PERSONA.format(target_language=self.target_language)

        rules = [
            f"- Active target language: {self.target_language} (strictly ONE language).",
            f"- Student's home language: {self.home_language}.",
            f"- Proficiency level: {self.proficiency_level}.",
            "- **IMPORTANT**: Begin the session by speaking in {self.home_language} to welcome the student, then transition to {self.target_language} for the lesson.",
            "- Always respond with a short, spoken-style Socratic turn.",
            "- Prefer questions over statements. Never lecture.",
            "- If the student speaks off-topic, gently redirect them back to language practice.",
        ]

        if self.scenario:
            rules.extend(
                [
                    f"- Scenario: {self.scenario.get('title', '')}",
                    f"- Your role: {self.scenario.get('ai_role', '')}",
                    f"- Student's task: {self.scenario.get('user_task', '')}",
                    f"- Target vocabulary for this scenario: {', '.join(self.scenario.get('target_lexicon', []))}.",
                    f"- Begin the roleplay by saying exactly: '{self.scenario.get('opening_line', '')}'",
                ]
            )
            completion = self.scenario.get("completion_conditions", [])
            if completion:
                rules.append(
                    f"- Help the student complete these steps: {', '.join(completion)}."
                )

        if self.weak_lexicon:
            rules.append(
                "- The student previously struggled with these terms: "
                f"{', '.join(self.weak_lexicon)}. "
                "Naturally prompt the user to use or practice these during today's roleplay."
            )

        if self.proficiency_level in {"A1", "A2"}:
            rules.append(
                f"- L1 SAFETY VALVE: If the student clearly expresses confusion in "
                f"{self.home_language}, you may give ONE brief 1-sentence clarification "
                f"in {self.home_language}, then immediately pivot back to 100% "
                f"{self.target_language}."
            )
        else:
            rules.append(
                f"- For {self.proficiency_level} learners, respond 100% in "
                f"{self.target_language} regardless of the input language."
            )

        return f"{base}\n\nRules:\n" + "\n".join(rules)

    def _record_milestone(self, event: str, detail: str) -> None:
        self.context_summary["milestones"].append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "detail": detail,
                "phase": self.phase.value,
            }
        )

    def _completion_conditions_met(self) -> list[str]:
        """Heuristically map used target lexicon to completion conditions."""
        conditions = self.scenario.get("completion_conditions", [])
        target_lexicon = self.scenario.get("target_lexicon", [])
        used = set(self.context_summary["used_vocabulary"])
        met: list[str] = []
        for idx, condition in enumerate(conditions):
            # Map each condition to the corresponding target lexicon item if available.
            if idx < len(target_lexicon) and target_lexicon[idx] in used:
                met.append(condition)
            elif used:
                # If we have any usage and the scenario has fewer conditions than words,
                # treat extra conditions as met one per additional unique target word.
                extra = len(used) - idx
                if extra > 0:
                    met.append(condition)
        return met

    def evaluate_session(self, milestone_completed: bool = False) -> dict[str, Any]:
        """
        Produce a lightweight CEFR-style post-session assessment.

        Scores are 0-5 integers across four standard speaking dimensions.
        """
        target_lexicon = self.scenario.get("target_lexicon", [])
        used_target = [
            w for w in target_lexicon if w in self.context_summary["used_vocabulary"]
        ]
        missed = [w for w in target_lexicon if w not in used_target]
        conditions = self.scenario.get("completion_conditions", [])
        met_conditions = self._completion_conditions_met()
        mistakes = self.context_summary.get("mistakes", [])
        user_turns = [t for t in self.transcript if t["role"] == "user"]

        # 0-5 score heuristics.
        if conditions:
            success_ratio = len(met_conditions) / len(conditions)
        else:
            success_ratio = 0.6
        communicative_success = min(5, max(1, int(round(5 * success_ratio))))

        if target_lexicon:
            lex_ratio = len(used_target) / len(target_lexicon)
        else:
            lex_ratio = 0.5
        lexical_resource = min(5, max(1, int(round(5 * lex_ratio))))

        grammatical_control = max(1, min(5, 5 - len(mistakes)))

        fluency = 3
        if len(user_turns) >= 3:
            fluency += 1
        if self.drift_strikes == 0:
            fluency += 1
        if self.drift_strikes >= 2:
            fluency -= 1
        fluency = max(1, min(5, fluency))

        detected_gaps: list[dict[str, str]] = []
        for word in missed:
            detected_gaps.append(
                {
                    "phrase": word,
                    "issue": f"The target phrase '{word}' was not used during the scenario.",
                    "type": "vocabulary",
                }
            )
        for mistake in mistakes:
            detected_gaps.append(
                {
                    "phrase": mistake["mistake"],
                    "issue": f"Recorded error: {mistake['mistake']} — correction: {mistake['correction']}",
                    "type": "grammar",
                }
            )

        return {
            "scenario_id": self.scenario.get("id", ""),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scores": {
                "communicative_success": communicative_success,
                "lexical_resource": lexical_resource,
                "grammatical_control": grammatical_control,
                "fluency": fluency,
            },
            "milestone_completed": milestone_completed,
            "target_lexicon_used": used_target,
            "missed_lexicon": missed,
            "detected_gaps": detected_gaps,
            "completion_conditions_met": met_conditions,
            "completion_conditions_total": len(conditions),
            "drift_strikes": self.drift_strikes,
        }

    def to_summary(self) -> dict[str, Any]:
        """Serialize the current state for the Jev Governor and clients."""
        return {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "phase": self.phase.value,
            "target_language": self.target_language,
            "home_language": self.home_language,
            "proficiency_level": self.proficiency_level,
            "session_length_minutes": self.session_length_minutes,
            "lockout_cooldown_minutes": self.lockout_cooldown_minutes,
            "scenario_id": self.scenario.get("id", ""),
            "vocabulary": list(self.vocabulary),
            "drift_strikes": self.drift_strikes,
            "is_locked_out": self.is_locked_out,
            "lockout_until": self.lockout_until.isoformat() if self.lockout_until else None,
            "context_summary": self.context_summary,
            "weak_lexicon": self.weak_lexicon,
        }
