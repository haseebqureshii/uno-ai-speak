from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

class CEFRLevel(str, Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"

class SessionStatus(str, Enum):
    WARMUP = "WARMUP"
    DRILL = "DRILL"
    ROLEPLAY = "ROLEPLAY"
    WRAPUP = "WRAPUP"
    PAUSE = "PAUSE"

class Speaker(str, Enum):
    USER = "USER"
    AI = "AI"

class StrikeSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"

class UserPreferences(BaseModel):
    user_id: str = Field(..., description="Unique user identifier")
    cefr_level: CEFRLevel = Field(..., description="User's current CEFR level")
    preferred_language: str = Field(..., description="Target language code (e.g., 'es')")
    timezone: str = Field("UTC", description="User's timezone")
    notification_preferences: Dict[str, bool] = Field(..., description="User's notification settings")
    auto_record: bool = Field(False, description="Whether to auto-record sessions")
    enable_socratic_check: bool = Field(True, description="Enable Socratic compliance check")
    enable_drift_check: bool = Field(True, description="Enable topic drift detection")
    max_strikes: int = Field(5, description="Maximum strikes before lockout")
    strike_lockout_duration_ms: int = Field(3600000, description="Lockout duration in milliseconds")
    srs_interval_pattern: str = Field("1,3,7,14,30", description="Comma-separated SRS review intervals in days")
    last_updated: datetime = Field(..., description="Last update timestamp")

    class Config:
        schema_extra = {
            "example": {
                "user_id": "usr_12345",
                "cefr_level": "B1",
                "preferred_language": "en",
                "timezone": "UTC",
                "notification_preferences": {"email": True, "push": False},
                "auto_record": True,
                "enable_socratic_check": True,
                "enable_drift_check": True,
                "max_strikes": 5,
                "strike_lockout_duration_ms": 3600000,
                "srs_interval_pattern": "1,3,7,14,30",
                "last_updated": "2026-10-15T10:30:00Z"
            }
        }

class ScheduledSession(BaseModel):
    scheduled_session_id: str = Field(..., description="Unique scheduled session identifier")
    user_id: str = Field(..., description="User identifier")
    scenario_id: str = Field(..., description="Target scenario identifier")
    cron_trigger: str = Field(..., description="Cron expression for session trigger")
    delivery_mode: str = Field(..., description="Delivery method: PUSH_NOTIFICATION or AUTOMATED_CALL")
    status: str = Field(..., description="Current status of the scheduled session")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        schema_extra = {
            "example": {
                "scheduled_session_id": "sess_67890",
                "user_id": "usr_12345",
                "scenario_id": "scn_11111",
                "cron_trigger": "0 9 * * 1-5",
                "delivery_mode": "PUSH_NOTIFICATION",
                "status": "SCHEDULED",
                "created_at": "2026-10-15T08:00:00Z",
                "updated_at": "2026-10-15T08:00:00Z"
            }
        }

class SessionInstance(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    scheduled_session_id: str = Field(..., description="Scheduled session identifier")
    user_id: str = Field(..., description="User identifier")
    status: SessionStatus = Field(..., description="Current session state")
    start_time: datetime = Field(..., description="Session start time")
    end_time: Optional[datetime] = Field(None, description="Session end time")
    duration_ms: Optional[int] = Field(None, description="Total session duration in milliseconds")
    transcript_url: Optional[str] = Field(None, description="URL to full transcript")
    assessment_url: Optional[str] = Field(None, description="URL to session assessment")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    strike_count: int = Field(0, description="Current number of strikes")
    is_locked: bool = Field(False, description="Whether the session is locked due to strikes")
    locked_until: Optional[datetime] = Field(None, description="Timestamp until which the session is locked")

    class Config:
        schema_extra = {
            "example": {
                "session_id": "inst_22222",
                "scheduled_session_id": "sess_67890",
                "user_id": "usr_12345",
                "status": "WARMUP",
                "start_time": "2026-10-15T09:00:00Z",
                "end_time": "2026-10-15T10:00:00Z",
                "duration_ms": 3600000,
                "transcript_url": "https://example.com/transcripts/inst_22222",
                "assessment_url": "https://example.com/assessments/inst_22222",
                "created_at": "2026-10-15T09:00:00Z",
                "updated_at": "2026-10-15T10:00:00Z",
                "strike_count": 0,
                "is_locked": False,
                "locked_until": None
            }
        }

class TranscriptChunk(BaseModel):
    chunk_id: str = Field(..., description="Unique chunk identifier")
    session_id: str = Field(..., description="Session identifier")
    text: str = Field(..., description="Transcript text")
    speaker: Speaker = Field(..., description="Speaker: USER or AI")
    start_ms: int = Field(..., description="Start time in milliseconds since session start")
    end_ms: int = Field(..., description="End time in milliseconds since session start")
    confidence: float = Field(1.0, description="ASR confidence score (0-1)")
    created_at: datetime = Field(..., description="Creation timestamp")

    class Config:
        schema_extra = {
            "example": {
                "chunk_id": "chunk_33333",
                "session_id": "inst_22222",
                "text": "¡Hola! ¿Qué le pongo hoy?",
                "speaker": "AI",
                "start_ms": 1200,
                "end_ms": 2800,
                "confidence": 0.95,
                "created_at": "2026-10-15T09:00:01Z"
            }
        }

class WeakLexicon(BaseModel):
    id: int = Field(..., description="Primary key")
    user_id: str = Field(..., description="User identifier")
    scenario_id: str = Field(..., description="Scenario identifier")
    word: str = Field(..., description="Target vocabulary word")
    language: str = Field(..., description="Language code")
    error_count: int = Field(0, description="Number of times this word was used incorrectly")
    last_reviewed_at: Optional[datetime] = Field(None, description="Last review timestamp")
    next_review_epoch_ms: int = Field(..., description="Next review time in milliseconds since epoch")
    ease_factor: float = Field(2.5, description="SM-2 algorithm ease factor")
    interval_days: int = Field(1, description="Current review interval in days")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        schema_extra = {
            "example": {
                "id": 101,
                "user_id": "usr_12345",
                "scenario_id": "scn_11111",
                "word": "restaurante",
                "language": "es",
                "error_count": 2,
                "last_reviewed_at": "2026-10-15T10:15:00Z",
                "next_review_epoch_ms": 1781000000000,
                "ease_factor": 2.3,
                "interval_days": 7,
                "created_at": "2026-10-15T09:30:00Z",
                "updated_at": "2026-10-15T10:15:00Z"
            }
        }

class StrikeLog(BaseModel):
    strike_id: str = Field(..., description="Unique strike identifier")
    user_id: str = Field(..., description="User identifier")
    session_id: Optional[str] = Field(None, description="Session identifier (nullable)")
    severity: StrikeSeverity = Field(..., description="Severity level of the strike")
    drift_type: Optional[str] = Field(None, description="Type of drift detected")
    context: str = Field(..., description="Context of the violation")
    resolved: bool = Field(False, description="Whether the strike has been resolved")
    resolved_by: Optional[str] = Field(None, description="User or system that resolved the strike")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        schema_extra = {
            "example": {
                "strike_id": "strike_44444",
                "user_id": "usr_12345",
                "session_id": "inst_22222",
                "severity": "MAJOR",
                "drift_type": "off_topic",
                "context": "User asked about weather instead of restaurant ordering",
                "resolved": False,
                "resolved_by": None,
                "created_at": "2026-10-15T09:15:00Z",
                "updated_at": "2026-10-15T09:15:00Z"
            }
        }

class SessionAssessment(BaseModel):
    assessment_id: str = Field(..., description="Unique assessment identifier")
    session_id: str = Field(..., description="Session identifier")
    user_id: str = Field(..., description="User identifier")
    fluency_score: Optional[float] = Field(None, description="Fluency score (0-5)")
    accuracy_score: Optional[float] = Field(None, description="Accuracy score (0-5)")
    coherence_score: Optional[float] = Field(None, description="Coherence score (0-5)")
    overall_score: Optional[float] = Field(None, description="Overall performance score (0-5)")
    feedback: str = Field(..., description="Detailed feedback for the user")
    created_at: datetime = Field(..., description="Creation timestamp")

    class Config:
        schema_extra = {
            "example": {
                "assessment_id": "assess_55555",
                "session_id": "inst_22222",
                "user_id": "usr_12345",
                "fluency_score": 4.2,
                "accuracy_score": 3.8,
                "coherence_score": 4.0,
                "overall_score": 4.0,
                "feedback": "Great job maintaining the conversation! Work on verb conjugations.",
                "created_at": "2026-10-15T10:05:00Z"
            }
        }

class DriftCheck(BaseModel):
    is_off_topic: bool = Field(..., description="Whether the conversation has drifted off-topic")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score (0-1)")
    detected_jailbreak: bool = Field(False, description="Whether a jailbreak attempt was detected")
    drift_type: Optional[str] = Field(None, description="Specific type of drift (e.g., off_topic, jailbreak)")
    context: str = Field(..., description="Full context of the user's utterance")
    current_text: str = Field(..., description="Current text being analyzed")

    class Config:
        schema_extra = {
            "example": {
                "is_off_topic": True,
                "confidence": 0.95,
                "detected_jailbreak": False,
                "drift_type": "off_topic",
                "context": "User asked about quantum physics in a restaurant roleplay scenario",
                "current_text": "Can you explain Schrödinger's cat?",
            }
        }

class SocraticCheck(BaseModel):
    is_question_led: bool = Field(..., description="Whether the AI response is question-led")
    directive_ratio: float = Field(..., ge=0, le=1, description="Ratio of directive to interrogative statements")
    recommended_interrupt: bool = Field(False, description="Whether the AI should interrupt and rephrase")
    context: str = Field(..., description="Full context of the AI's generated response")
    current_text: str = Field(..., description="Current text being evaluated")

    class Config:
        schema_extra = {
            "example": {
                "is_question_led": False,
                "directive_ratio": 0.8,
                "recommended_interrupt": True,
                "context": "You should always order tapas in Spain. It's the best choice.",
                "current_text": "You should always order tapas in Spain.",
            }
        }
